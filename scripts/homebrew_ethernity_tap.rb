class Ethernity < Formula
  include Language::Python::Virtualenv

  desc "Secure, offline-recoverable backup system with QR-based recovery documents"
  homepage "https://github.com/MinorGlitch/ethernity"
  url "https://github.com/MinorGlitch/ethernity/archive/refs/tags/v0.9.1.tar.gz"
  sha256 "20386ed7847b01298b43f7cbe653b09f98be77fa0b6a0569c09c0bad54382efc"
  license "GPL-3.0-or-later"

  depends_on "pkgconf" => :build
  depends_on "pillow"
  depends_on "python@3.13"

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

  resource "greenlet" do
    url "https://files.pythonhosted.org/packages/a3/51/1664f6b78fc6ebbd98019a1fd730e83fa78f2db7058f72b1463d3612b8db/greenlet-3.3.2.tar.gz"
    sha256 "2eaf067fc6d886931c7962e8c6bede15d2f01965560f3359b27c80bde2d151f2"
  end

  resource "jinja2" do
    url "https://files.pythonhosted.org/packages/62/a1/3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/jinja2-3.1.6-py3-none-any.whl"
    sha256 "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67"
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

  resource "markupsafe" do
    url "https://files.pythonhosted.org/packages/7e/99/7690b6d4034fffd95959cbe0c02de8deb3098cc577c67bb6a24fe5d7caa7/markupsafe-3.0.3.tar.gz"
    sha256 "722695808f4b6457b320fdc131280796bdceb04ab50fe1795cd540799ebe1698"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/b3/38/89ba8ad64ae25be8de66a6d463314cf1eb366222074cfda9ee839c56a4b4/mdurl-0.1.2-py3-none-any.whl"
    sha256 "84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8"
  end

  resource "platformdirs" do
    url "https://files.pythonhosted.org/packages/48/31/05e764397056194206169869b50cf2fee4dbbbc71b344705b9c0d878d4d8/platformdirs-4.9.2-py3-none-any.whl"
    sha256 "9170634f126f8efdae22fb58ae8a0eaa86f38365bc57897a6c4f781d1f5875bd"
  end

  resource "prompt-toolkit" do
    url "https://files.pythonhosted.org/packages/84/03/0d3ce49e2505ae70cf43bc5bb3033955d2fc9f932163e84dc0779cc47f48/prompt_toolkit-3.0.52-py3-none-any.whl"
    sha256 "9aac639a3bbd33284347de5ad8d68ecc044b91a762dc39b7c21095fcd6a19955"
  end

  resource "pycryptodome" do
    url "https://files.pythonhosted.org/packages/8e/a6/8452177684d5e906854776276ddd34eca30d1b1e15aa1ee9cefc289a33f5/pycryptodome-3.23.0.tar.gz"
    sha256 "447700a657182d60338bab09fdb27518f8856aecd80ae4c6bdddb67ff5da44ef"
  end

  if OS.mac?
    resource "playwright" do
      url "https://files.pythonhosted.org/packages/e1/ee/3ce6209c9c74a650aac9028c621f357a34ea5cd4d950700f8e2c4b7fe2c4/playwright-1.58.0-py3-none-macosx_11_0_universal2.whl"
      sha256 "185e0132578733d02802dfddfbbc35f42be23a45ff49ccae5081f25952238117"
    end

    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/f7/6e/3095678ee12f0401e1de17f4d6993783b20a4b807daf69e23b170724e5f4/pyrage-1.3.0-cp39-abi3-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl"
      sha256 "907901ada8d63d674cc9005889150846c7349ef587ee8bf5e9278b79c54b4679"
    end

  elsif Hardware::CPU.arm?
    resource "playwright" do
      url "https://files.pythonhosted.org/packages/d9/a6/0e66ad04b6d3440dae73efb39540c5685c5fc95b17c8b29340b62abbd952/playwright-1.58.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
      sha256 "8f9999948f1ab541d98812de25e3a8c410776aa516d948807140aff797b4bffa"
    end

    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/3b/e7/f515fbc972a5d83e9fa82d1c23a16f733f4dd6c2c6ae33d9054ca04a8d92/pyrage-1.3.0-cp39-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
      sha256 "ea452cb9c9c47083a96b309467dea5614d12530e1de4b6585f10aa04d3d19d1c"
    end

  else
    resource "playwright" do
      url "https://files.pythonhosted.org/packages/f1/af/009958cbf23fac551a940d34e3206e6c7eed2b8c940d0c3afd1feb0b0589/playwright-1.58.0-py3-none-manylinux1_x86_64.whl"
      sha256 "c95568ba1eda83812598c1dc9be60b4406dffd60b149bc1536180ad108723d6b"
    end

    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/38/f3/e91bf604fd40c42c60e8f95075cddb0b85d0bdf452f736b533b1bad550e0/pyrage-1.3.0-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
      sha256 "ab066b22925c5a0ec5fead2e21e4586b21d5da730055c7e46caa978bd99de936"
    end
  end

  resource "pyee" do
    url "https://files.pythonhosted.org/packages/a0/c4/b4d4827c93ef43c01f599ef31453ccc1c132b353284fc6c87d535c233129/pyee-13.0.1-py3-none-any.whl"
    sha256 "af2f8fede4171ef667dfded53f96e2ed0d6e6bd7ee3bb46437f77e3b57689228"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/c7/21/705964c7812476f378728bdf590ca4b771ec72385c533964653c68e86bdc/pygments-2.19.2-py3-none-any.whl"
    sha256 "86540386c03d588bb81d44bc3928634ff26449851e99741617ecb9037ee5ec0b"
  end

  resource "pypdf" do
    url "https://files.pythonhosted.org/packages/df/df/38b06d6e74646a4281856920a11efb431559bdeb643bf1e192bff5e29082/pypdf-6.7.2-py3-none-any.whl"
    sha256 "331b63cd66f63138f152a700565b3e0cebdf4ec8bec3b7594b2522418782f1f3"
  end

  resource "python-docx" do
    url "https://files.pythonhosted.org/packages/d0/00/1e03a4989fa5795da308cd774f05b704ace555a70f9bf9d3be057b680bcf/python_docx-1.2.0-py3-none-any.whl"
    sha256 "3fd478f3250fbbbfd3b94fe1e985955737c145627498896a8a6bf81f4baf66c7"
  end

  resource "questionary" do
    url "https://files.pythonhosted.org/packages/3c/26/1062c7ec1b053db9e499b4d2d5bc231743201b74051c973dadeac80a8f43/questionary-2.1.1-py3-none-any.whl"
    sha256 "a51af13f345f1cdea62347589fbb6df3b290306ab8930713bfae4d475a7d4a59"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/14/25/b208c5683343959b670dc001595f2f3737e051da617f66c31f7c4fa93abc/rich-14.3.3-py3-none-any.whl"
    sha256 "793431c1f8619afa7d3b52b2cdec859562b950ea0d4b6b505397612db8d5362d"
  end

  resource "segno" do
    url "https://files.pythonhosted.org/packages/d6/02/12c73fd423eb9577b97fc1924966b929eff7074ae6b2e15dd3d30cb9e4ae/segno-1.6.6-py3-none-any.whl"
    sha256 "28c7d081ed0cf935e0411293a465efd4d500704072cdb039778a2ab8736190c7"
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/4a/91/48db081e7a63bb37284f9fbcefda7c44c277b18b0e13fbc36ea2335b71e6/typer-0.24.1-py3-none-any.whl"
    sha256 "112c1f0ce578bfb4cab9ffdabc68f031416ebcc216536611ba21f04e9aa84c9e"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/18/67/36e9267722cc04a6b9f15c7f3441c2363321a3ea07da7ae0c0707beb2a9c/typing_extensions-4.15.0-py3-none-any.whl"
    sha256 "f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548"
  end

  resource "wcwidth" do
    url "https://files.pythonhosted.org/packages/68/5a/199c59e0a824a3db2b89c5d2dade7ab5f9624dbf6448dc291b46d5ec94d3/wcwidth-0.6.0-py3-none-any.whl"
    sha256 "1a3a1e510b553315f8e146c54764f4fb6264ffad731b3d78088cdb1478ffbdad"
  end

  if OS.mac?
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
  end

  test do
    ENV["ETHERNITY_SKIP_PLAYWRIGHT_INSTALL"] = "1"
    assert_match "Usage", shell_output("#{bin}/ethernity --help")
  end
end
