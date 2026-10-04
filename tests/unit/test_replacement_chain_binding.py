from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from ethernity.crypto import sharding
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.workflows.recovery import keys
from ethernity.workflows.replacement_recovery import service
from ethernity.workflows.shared.operation_types import ReplacementRecoveryOperationRequest

SIGNING_SEED = b"s" * 32
SIGN_PUB = derive_public_key(SIGNING_SEED)


@dataclass
class ReplacementChain:
    plan: SimpleNamespace
    chain: SimpleNamespace
    output_dir: Path
    rendered_frames: list[Frame]

    def execute(
        self,
        *,
        passphrase_frames: list[Frame] | None = None,
        signing_key_frames: list[Frame] | None = None,
        compatible_replacements: bool = False,
    ):
        return service._replacement_from_plan(
            plan=self.plan,
            config=SimpleNamespace(
                cli_defaults=SimpleNamespace(backup=SimpleNamespace(qr_payload_codec="raw"))
            ),
            args=ReplacementRecoveryOperationRequest(
                output_dir=str(self.output_dir),
                shard_threshold=2,
                shard_count=3,
                passphrase_replacement_count=1 if compatible_replacements else None,
                create_signing_key_shards=not compatible_replacements,
                allow_stale_head=True,
                quiet=True,
            ),
            passphrase_shard_frames=passphrase_frames or [],
            signing_key_frames=signing_key_frames or [],
            manifest_signing_seed=service._UNSET,
            debug=False,
        )


@pytest.fixture
def replacement_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReplacementChain:
    plan = SimpleNamespace(
        doc_id=b"r" * 8,
        doc_hash=b"r" * 32,
        passphrase="chain-replacement-passphrase",
        auth_payload=SimpleNamespace(sign_pub=SIGN_PUB),
    )
    chain = SimpleNamespace(
        manifest=SimpleNamespace(signing_seed=SIGNING_SEED),
        head=SimpleNamespace(doc_id=b"h" * 8, doc_hash=b"h" * 32),
        selected_extension_index=1,
        selected_extension_doc_hash=(b"h" * 32).hex(),
    )
    rendered_frames: list[Frame] = []

    def capture_shard(shard: sharding.ShardPayload, *, doc_id, output_dir, **kwargs):
        rendered_frames.append(_frame_for_shard(shard, doc_id=doc_id))
        output = Path(output_dir) / f"{shard.key_type}-{shard.share_index}.pdf"
        output.write_bytes(b"rendered-shard")
        return str(output)

    monkeypatch.setattr(service, "_recover_replacement_chain", lambda *args, **kwargs: chain)
    monkeypatch.setattr(service, "render_shard_document", capture_shard)
    return ReplacementChain(plan, chain, tmp_path / "replacement", rendered_frames)


def _frame_for_shard(shard: sharding.ShardPayload, *, doc_id: bytes) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=sharding.encode_shard_payload(shard),
    )


def _passphrase_frames(chain: ReplacementChain, *, doc_hash: bytes | None = None) -> list[Frame]:
    payloads = sharding.split_passphrase(
        chain.plan.passphrase,
        threshold=2,
        shares=3,
        doc_hash=doc_hash or chain.plan.doc_hash,
        sign_priv=SIGNING_SEED,
        sign_pub=SIGN_PUB,
    )
    return [_frame_for_shard(shard, doc_id=chain.plan.doc_id) for shard in payloads[:2]]


@pytest.mark.parametrize("sealed", [False, True])
def test_new_sets_always_unlock_original_root(
    replacement_chain: ReplacementChain, sealed: bool
) -> None:
    chain = replacement_chain
    signing_key_frames: list[Frame] = []
    if sealed:
        chain.chain.manifest.signing_seed = None
        chain.chain.head = SimpleNamespace(doc_id=chain.plan.doc_id, doc_hash=chain.plan.doc_hash)
        chain.chain.selected_extension_index = None
        chain.chain.selected_extension_doc_hash = None
        existing_signing_payloads = sharding.split_signing_seed(
            SIGNING_SEED,
            threshold=2,
            shares=3,
            doc_hash=chain.plan.doc_hash,
            sign_priv=SIGNING_SEED,
            sign_pub=SIGN_PUB,
        )
        signing_key_frames = [
            _frame_for_shard(shard, doc_id=chain.plan.doc_id)
            for shard in existing_signing_payloads[:2]
        ]

    result = chain.execute(signing_key_frames=signing_key_frames)

    assert result.doc_id == chain.plan.doc_id
    assert result.doc_hash == chain.plan.doc_hash
    assert result.selected_extension_index == chain.chain.selected_extension_index
    assert result.selected_extension_doc_hash == chain.chain.selected_extension_doc_hash
    binding = {
        "expected_doc_id": chain.plan.doc_id,
        "expected_doc_hash": chain.plan.doc_hash,
        "expected_sign_pub": SIGN_PUB,
        "allow_unsigned": False,
    }
    passphrase_frames = chain.rendered_frames[:3]
    signing_frames = chain.rendered_frames[3:]
    assert (
        keys.passphrase_from_shard_frames(passphrase_frames[:2], **binding) == chain.plan.passphrase
    )
    assert keys.signing_seed_from_shard_frames(signing_frames[:2], **binding) == SIGNING_SEED

    with pytest.raises(ValueError, match="shard doc_hash does not match"):
        keys.passphrase_from_shard_frames(
            passphrase_frames[:2],
            **{**binding, "expected_doc_hash": b"h" * 32},
        )


def test_compatible_replacement_at_extension_uses_original_root_set(
    replacement_chain: ReplacementChain,
) -> None:
    chain = replacement_chain
    old_frames = _passphrase_frames(chain)

    chain.execute(passphrase_frames=old_frames, compatible_replacements=True)

    assert len(chain.rendered_frames) == 1
    replacement = chain.rendered_frames[0]
    assert sharding.decode_shard_payload(replacement.data).share_index == 3
    assert (
        keys.passphrase_from_shard_frames(
            [old_frames[0], replacement],
            expected_doc_id=chain.plan.doc_id,
            expected_doc_hash=chain.plan.doc_hash,
            expected_sign_pub=SIGN_PUB,
            allow_unsigned=False,
        )
        == chain.plan.passphrase
    )


@pytest.mark.parametrize("wrong_binding", [b"h" * 32, b"x" * 32])
def test_compatible_replacement_rejects_head_or_unrelated_root_binding(
    replacement_chain: ReplacementChain, wrong_binding: bytes
) -> None:
    chain = replacement_chain
    frames = _passphrase_frames(chain, doc_hash=wrong_binding)

    with pytest.raises(ValueError, match="shard doc_hash does not match"):
        chain.execute(passphrase_frames=frames, compatible_replacements=True)

    assert not chain.output_dir.exists()
    assert not chain.rendered_frames


def test_sealed_replacement_rejects_signing_key_shards_with_wrong_root_hash(
    replacement_chain: ReplacementChain,
) -> None:
    chain = replacement_chain
    chain.chain.manifest.signing_seed = None
    chain.chain.head = SimpleNamespace(doc_id=chain.plan.doc_id, doc_hash=chain.plan.doc_hash)
    chain.chain.selected_extension_index = None
    chain.chain.selected_extension_doc_hash = None
    payloads = sharding.split_signing_seed(
        SIGNING_SEED,
        threshold=2,
        shares=3,
        doc_hash=b"h" * 32,
        sign_priv=SIGNING_SEED,
        sign_pub=SIGN_PUB,
    )
    frames = [_frame_for_shard(shard, doc_id=chain.plan.doc_id) for shard in payloads[:2]]

    with pytest.raises(ValueError, match="shard doc_hash does not match"):
        chain.execute(signing_key_frames=frames)

    assert not chain.output_dir.exists()
