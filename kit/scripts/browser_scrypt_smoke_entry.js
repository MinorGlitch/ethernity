import { decryptAgePassphrase } from "../lib/age_scrypt.js";

function bytesFromBase64(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function run() {
  const keepAlive = setInterval(() => {}, 100);
  const ciphertext = bytesFromBase64(document.body.dataset.ciphertext);
  const passphrase = document.body.dataset.passphrase;
  try {
    const plaintext = await decryptAgePassphrase(ciphertext, passphrase);
    document.body.textContent = new TextDecoder().decode(plaintext);
  } catch (err) {
    document.body.textContent = `worker-error:${err instanceof Error ? err.message : String(err)}`;
  } finally {
    clearInterval(keepAlive);
  }
}

void run();
