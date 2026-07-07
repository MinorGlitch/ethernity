class Ethernity < Formula
  include Language::Python::Virtualenv

  desc "Secure, offline-recoverable backup system with QR-based recovery documents"
  homepage "https://github.com/MinorGlitch/ethernity"
  url "https://github.com/MinorGlitch/ethernity/archive/refs/tags/v0.9.1.tar.gz"
  sha256 "9efc1b94b7c8736505359143dee5ffa0e4b641fadcbdc2d8f5a96c13d97457c5"
  license "GPL-3.0-or-later"

  depends_on "pkgconf" => :build
  depends_on "pillow"
  depends_on "python@3.13"
  uses_from_macos "libxml2"
  uses_from_macos "libxslt"

  resource "cbor2" do
    url "https://files.pythonhosted.org/packages/d6/4f/101071f880b4da05771128c0b89f41e334cff044dee05fb013c8f4be661c/cbor2-5.8.0-py3-none-any.whl"
    sha256 "3727d80f539567b03a7aa11890e57798c67092c38df9e6c23abb059e0f65069c"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/98/78/01c019cdb5d6498122777c1a43056ebb3ebfeef2076d9d026bfe15583b2b/click-8.3.1-py3-none-any.whl"
    sha256 "981153a64e25f12d547d3426c367a4857371575ee7ad18df2a6183ab0545b2a6"
  end

  resource "defusedxml" do
    url "https://files.pythonhosted.org/packages/07/6c/aa3f2f849e01cb6a001cd8554a88d4c77c5c1a31c95bdf1cf9301e6d9ef4/defusedxml-0.7.1-py2.py3-none-any.whl"
    sha256 "a352e7e428770286cc899e2542b6cdaedb2b4953ff269a210103ec58f6198a61"
  end

  resource "fonttools" do
    url "https://files.pythonhosted.org/packages/c7/4e/ce75a57ff3aebf6fc1f4e9d508b8e5810618a33d900ad6c19eb30b290b97/fonttools-4.61.1-py3-none-any.whl"
    sha256 "17d2bf5d541add43822bcf0c43d7d847b160c9bb01d15d5007d84e2217aaa371"
  end

  resource "fpdf2" do
    url "https://files.pythonhosted.org/packages/06/93/af9bff8ea01bf0895b4ebf0641da613e4e342112ee82d50642638f763239/fpdf2-2.8.6-py3-none-any.whl"
    sha256 "464658b896c6b0fcbf883abb316b8f0a52d582eb959d71822ba254d6c790bfdd"
  end

  if OS.mac?
    resource "lxml" do
      url "https://files.pythonhosted.org/packages/53/fd/4e8f0540608977aea078bf6d79f128e0e2c2bba8af1acf775c30baa70460/lxml-6.0.2-cp313-cp313-macosx_10_13_universal2.whl"
      sha256 "9b33d21594afab46f37ae58dfadd06636f154923c4e8a4d754b0127554eb2e77"
    end
  elsif Hardware::CPU.arm?
    resource "lxml" do
      url "https://files.pythonhosted.org/packages/25/2e/4efa677fa6b322013035d38016f6ae859d06cac67437ca7dc708a6af7028/lxml-6.0.2-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.whl"
      sha256 "1941354d92699fb5ffe6ed7b32f9649e43c2feb4b97205f75866f7d21aa91452"
    end
  else
    resource "lxml" do
      url "https://files.pythonhosted.org/packages/ce/0f/526e78a6d38d109fdbaa5049c62e1d32fdd70c75fb61c4eadf3045d3d124/lxml-6.0.2-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
      sha256 "bb2f6ca0ae2d983ded09357b84af659c954722bbf04dea98030064996d156048"
    end
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/94/54/e7d793b573f298e1c9013b8c4dade17d481164aa517d1d7148619c2cedbf/markdown_it_py-4.0.0-py3-none-any.whl"
    sha256 "87327c59b172c5011896038353a81343b6754500a08cd7a4973bb48c6d578147"
  end

  resource "mdit-py-plugins" do
    url "https://files.pythonhosted.org/packages/a5/69/6da5581c6a7fede7dc261bf4e67d6adca4196f176b43288b55b3db395b6e/mdit_py_plugins-0.6.1-py3-none-any.whl"
    sha256 "214c82fb2ac524472ab6a5bcab1de80f73b50443e187f401bfd77efbc7c6481d"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/b3/38/89ba8ad64ae25be8de66a6d463314cf1eb366222074cfda9ee839c56a4b4/mdurl-0.1.2-py3-none-any.whl"
    sha256 "84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8"
  end

  resource "platformdirs" do
    url "https://files.pythonhosted.org/packages/48/31/05e764397056194206169869b50cf2fee4dbbbc71b344705b9c0d878d4d8/platformdirs-4.9.2-py3-none-any.whl"
    sha256 "9170634f126f8efdae22fb58ae8a0eaa86f38365bc57897a6c4f781d1f5875bd"
  end

  resource "pycryptodome" do
    url "https://files.pythonhosted.org/packages/8e/a6/8452177684d5e906854776276ddd34eca30d1b1e15aa1ee9cefc289a33f5/pycryptodome-3.23.0.tar.gz"
    sha256 "447700a657182d60338bab09fdb27518f8856aecd80ae4c6bdddb67ff5da44ef"
  end

  if OS.mac?
    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/f7/6e/3095678ee12f0401e1de17f4d6993783b20a4b807daf69e23b170724e5f4/pyrage-1.3.0-cp39-abi3-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl"
      sha256 "907901ada8d63d674cc9005889150846c7349ef587ee8bf5e9278b79c54b4679"
    end
  elsif Hardware::CPU.arm?
    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/3b/e7/f515fbc972a5d83e9fa82d1c23a16f733f4dd6c2c6ae33d9054ca04a8d92/pyrage-1.3.0-cp39-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
      sha256 "ea452cb9c9c47083a96b309467dea5614d12530e1de4b6585f10aa04d3d19d1c"
    end
  else
    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/38/f3/e91bf604fd40c42c60e8f95075cddb0b85d0bdf452f736b533b1bad550e0/pyrage-1.3.0-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
      sha256 "ab066b22925c5a0ec5fead2e21e4586b21d5da730055c7e46caa978bd99de936"
    end
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/c7/21/705964c7812476f378728bdf590ca4b771ec72385c533964653c68e86bdc/pygments-2.19.2-py3-none-any.whl"
    sha256 "86540386c03d588bb81d44bc3928634ff26449851e99741617ecb9037ee5ec0b"
  end

  resource "pypdf" do
    url "https://files.pythonhosted.org/packages/df/df/38b06d6e74646a4281856920a11efb431559bdeb643bf1e192bff5e29082/pypdf-6.7.2-py3-none-any.whl"
    sha256 "331b63cd66f63138f152a700565b3e0cebdf4ec8bec3b7594b2522418782f1f3"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/fd/7b/122376b1fd3c62c1ed9dc80c931ace4844b3c55407b6fb2d199377c9736f/pydantic-2.13.4-py3-none-any.whl"
    sha256 "45a282cde31d808236fd7ea9d919b128653c8b38b393d1c4ab335c62924d9aba"
  end

  resource "pydantic-core" do
    url "https://files.pythonhosted.org/packages/9d/56/921726b776ace8d8f5db44c4ef961006580d91dc52b803c489fafd1aa249/pydantic_core-2.46.4.tar.gz"
    sha256 "62f875393d7f270851f20523dd2e29f082bcc82292d66db2b64ea71f64b6e1c1"
  end

  resource "python-docx" do
    url "https://files.pythonhosted.org/packages/d0/00/1e03a4989fa5795da308cd774f05b704ace555a70f9bf9d3be057b680bcf/python_docx-1.2.0-py3-none-any.whl"
    sha256 "3fd478f3250fbbbfd3b94fe1e985955737c145627498896a8a6bf81f4baf66c7"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/14/25/b208c5683343959b670dc001595f2f3737e051da617f66c31f7c4fa93abc/rich-14.3.3-py3-none-any.whl"
    sha256 "793431c1f8619afa7d3b52b2cdec859562b950ea0d4b6b505397612db8d5362d"
  end

  resource "segno" do
    url "https://files.pythonhosted.org/packages/d6/02/12c73fd423eb9577b97fc1924966b929eff7074ae6b2e15dd3d30cb9e4ae/segno-1.6.6-py3-none-any.whl"
    sha256 "28c7d081ed0cf935e0411293a465efd4d500704072cdb039778a2ab8736190c7"
  end

  resource "annotated-types" do
    url "https://files.pythonhosted.org/packages/78/b6/6307fbef88d9b5ee7421e68d78a9f162e0da4900bc5f5793f6d3d0e34fb8/annotated_types-0.7.0-py3-none-any.whl"
    sha256 "1f02e8b43a8fbbc3f3e0d4f0f4bfc8131bcb4eebe8849b8e5c773f3a1c582a53"
  end

  resource "textual" do
    url "https://files.pythonhosted.org/packages/fb/be/35261223d9416a0751cdff1c7b4a6f881387218a12d439fe22fefebc8c04/textual-8.2.8-py3-none-any.whl"
    sha256 "267375fd402dc8d981457212efa71f0e3365fd17bba144ba9bb3ed7563cb374a"
  end

  resource "typing-inspection" do
    url "https://files.pythonhosted.org/packages/dc/9b/47798a6c91d8bdb567fe2698fe81e0c6b7cb7ef4d13da4114b41d239f65d/typing_inspection-0.4.2-py3-none-any.whl"
    sha256 "4ed1cacbdc298c220f1bd249ed5287caa16f34d44ef4e9c3d0cbad5b521545e7"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/18/67/36e9267722cc04a6b9f15c7f3441c2363321a3ea07da7ae0c0707beb2a9c/typing_extensions-4.15.0-py3-none-any.whl"
    sha256 "f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548"
  end

  if OS.mac? && Hardware::CPU.arm?
    resource "zxing-cpp" do
      url "https://files.pythonhosted.org/packages/52/7e/971bb37b9091b02fd12f7c13745335a77a8e9e907abc3e0530ff9c4e6b32/zxing_cpp-3.0.0-cp313-cp313-macosx_11_0_arm64.whl"
      sha256 "c4d44e63c0cb06df1d7ab636018b3e7139d5b010c22a5dcb18f3badfa29e1e1c"
    end
  elsif OS.mac?
    resource "zxing-cpp" do
      url "https://files.pythonhosted.org/packages/a0/c4/c4f276e43c4df74896b7cac2a3e5deabaf743e8256ee6736380d64f7295b/zxing_cpp-3.0.0-cp313-cp313-macosx_10_13_x86_64.whl"
      sha256 "26ee52319b545a0db5adc19c682d5bd7efa210456daff0293f5cc78311c52d90"
    end
  elsif Hardware::CPU.intel?
    resource "zxing-cpp" do
      url "https://files.pythonhosted.org/packages/a3/ac/ae87a5ed87a7623e18a986e4394c3e12a5fa0f4fa55dae3be7f5ca6ef392/zxing_cpp-3.0.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
      sha256 "0a96c8eaf1adff4c5aaf99c74d2b5ce3d542d44c21f964ac3f70eaaefcdc141e"
    end
  else
    resource "zxing-cpp" do
      url "https://files.pythonhosted.org/packages/f1/c6/ac2a12cdc2b1c296804fc6a65bf112b607825ca7f47742a5aca541134711/zxing_cpp-3.0.0.tar.gz"
      sha256 "703353304de24d947bd68044fac4e062953a7b64029de6941ba8ffeb4476b60d"
    end
  end

  def install
    venv = virtualenv_create(libexec, "python3.13")

    resources.each do |resource|
      if resource.url&.end_with?(".whl")
        resource.fetch
        wheel_name = File.basename(resource.url)
        wheel_path = buildpath/wheel_name
        cp resource.cached_download, wheel_path
        venv.pip_install wheel_path
      else
        resource.stage do
          venv.pip_install Pathname.pwd
        end
      end
    end

    venv.pip_install_and_link buildpath
    smoke_root = "tests/fixtures/v1_2/extension_golden/raw/gzip_replacement_chain/chain/" \
      "qr_document.pdf"
    smoke_extension = Dir[
      "tests/fixtures/v1_2/extension_golden/raw/gzip_replacement_chain/chain/" \
        "extensions/01/qr_document-01-*.pdf"
    ].first
    odie "missing extension smoke fixture" if smoke_extension.nil?
    pkgshare.install smoke_root => "smoke/extension-root.pdf"
    pkgshare.install smoke_extension => "smoke/extension-01.pdf"
  end

  test do
    assert_match "Usage", shell_output("#{bin}/ethernity --help")
    system bin/"ethernity", "run", "restore",
      "--scan", pkgshare/"smoke/extension-root.pdf",
      "--scan", pkgshare/"smoke/extension-01.pdf",
      "--passphrase", "stable-v1_2-extension-passphrase",
      "--output", testpath/"recovered",
      "--yes"
    assert_path_exists testpath/"recovered"
  end
end
