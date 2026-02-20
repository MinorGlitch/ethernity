class Ethernity < Formula
  include Language::Python::Virtualenv

  desc "Secure, offline-recoverable backup system with QR-based recovery documents"
  homepage "https://github.com/MinorGlitch/ethernity"
  url "https://github.com/MinorGlitch/ethernity/archive/refs/tags/v0.2.1.tar.gz"
  sha256 "8f5e1848ca6c689287557a383cd787aea1cb440f7de45b7850d14b1c38fb34fb"
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
    url "https://files.pythonhosted.org/packages/35/a7/8532d8fffe6d1c388ad4941d678dd0da4d8da80434f2dbf4f35de0fa8029/fpdf2-2.8.5-py3-none-any.whl"
    sha256 "2356b94e2a5fcbd1fe53ac5cbb83494e9003308860ab180050255ba50961d913"
  end

  resource "greenlet" do
    url "https://files.pythonhosted.org/packages/c7/e5/40dbda2736893e3e53d25838e0f19a2b417dfc122b9989c91918db30b5d3/greenlet-3.3.0.tar.gz"
    sha256 "a82bb225a4e9e4d653dd2fb7b8b2d36e4fb25bc0165422a11e48b88e9e6f78fb"
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
    url "https://files.pythonhosted.org/packages/cb/28/3bfe2fa5a7b9c46fe7e13c97bda14c895fb10fa2ebf1d0abb90e0cea7ee1/platformdirs-4.5.1-py3-none-any.whl"
    sha256 "d03afa3963c806a9bed9d5125c8f4cb2fdaf74a55ab60e5d59b3fde758104d31"
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
      url "https://files.pythonhosted.org/packages/60/bd/5563850322a663956c927eefcf1457d12917e8f118c214410e815f2147d1/playwright-1.57.0-py3-none-macosx_11_0_universal2.whl"
      sha256 "99104771abc4eafee48f47dac2369e0015516dc1ce8c409807d2dd440828b9a4"
    end

    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/f7/6e/3095678ee12f0401e1de17f4d6993783b20a4b807daf69e23b170724e5f4/pyrage-1.3.0-cp39-abi3-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl"
      sha256 "907901ada8d63d674cc9005889150846c7349ef587ee8bf5e9278b79c54b4679"
    end

  elsif Hardware::CPU.arm?
    resource "playwright" do
      url "https://files.pythonhosted.org/packages/83/d7/b72eb59dfbea0013a7f9731878df8c670f5f35318cedb010c8a30292c118/playwright-1.57.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
      sha256 "38a1bae6c0a07839cdeaddbc0756b3b2b85e476c07945f64ece08f1f956a86f1"
    end

    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/3b/e7/f515fbc972a5d83e9fa82d1c23a16f733f4dd6c2c6ae33d9054ca04a8d92/pyrage-1.3.0-cp39-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
      sha256 "ea452cb9c9c47083a96b309467dea5614d12530e1de4b6585f10aa04d3d19d1c"
    end

  else
    resource "playwright" do
      url "https://files.pythonhosted.org/packages/56/61/3a803cb5ae0321715bfd5247ea871d25b32c8f372aeb70550a90c5f586df/playwright-1.57.0-py3-none-manylinux1_x86_64.whl"
      sha256 "284ed5a706b7c389a06caa431b2f0ba9ac4130113c3a779767dda758c2497bb1"
    end

    resource "pyrage" do
      url "https://files.pythonhosted.org/packages/38/f3/e91bf604fd40c42c60e8f95075cddb0b85d0bdf452f736b533b1bad550e0/pyrage-1.3.0-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
      sha256 "ab066b22925c5a0ec5fead2e21e4586b21d5da730055c7e46caa978bd99de936"
    end
  end

  resource "pyee" do
    url "https://files.pythonhosted.org/packages/9b/4d/b9add7c84060d4c1906abe9a7e5359f2a60f7a9a4f67268b2766673427d8/pyee-13.0.0-py3-none-any.whl"
    sha256 "48195a3cddb3b1515ce0695ed76036b5ccc2ef3a9f963ff9f77aec0139845498"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/c7/21/705964c7812476f378728bdf590ca4b771ec72385c533964653c68e86bdc/pygments-2.19.2-py3-none-any.whl"
    sha256 "86540386c03d588bb81d44bc3928634ff26449851e99741617ecb9037ee5ec0b"
  end

  resource "pypdf" do
    url "https://files.pythonhosted.org/packages/de/db/f2e7703791a1f32532618b82789ddddb7173b9e22d97e34cc11950d8e330/pypdf-6.5.0-py3-none-any.whl"
    sha256 "9cef8002aaedeecf648dfd9ff1ce38f20ae8d88e2534fced6630038906440b25"
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
    url "https://files.pythonhosted.org/packages/25/7a/b0178788f8dc6cafce37a212c99565fa1fe7872c70c6c9c1e1a372d9d88f/rich-14.2.0-py3-none-any.whl"
    sha256 "76bc51fe2e57d2b1be1f96c524b890b816e334ab4c1e45888799bfaab0021edd"
  end

  resource "segno" do
    url "https://files.pythonhosted.org/packages/d6/02/12c73fd423eb9577b97fc1924966b929eff7074ae6b2e15dd3d30cb9e4ae/segno-1.6.6-py3-none-any.whl"
    sha256 "28c7d081ed0cf935e0411293a465efd4d500704072cdb039778a2ab8736190c7"
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/e1/e4/5ebc1899d31d2b1601b32d21cfb4bba022ae6fce323d365f0448031b1660/typer-0.21.0-py3-none-any.whl"
    sha256 "c79c01ca6b30af9fd48284058a7056ba0d3bf5cf10d0ff3d0c5b11b68c258ac6"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/18/67/36e9267722cc04a6b9f15c7f3441c2363321a3ea07da7ae0c0707beb2a9c/typing_extensions-4.15.0-py3-none-any.whl"
    sha256 "f0fa19c6845758ab08074a0cfa8b7aecb71c999ca73d62883bc25cc018c4e548"
  end

  resource "wcwidth" do
    url "https://files.pythonhosted.org/packages/af/b5/123f13c975e9f27ab9c0770f514345bd406d0e8d3b7a0723af9d43f710af/wcwidth-0.2.14-py2.py3-none-any.whl"
    sha256 "a7bb560c8aee30f9957e5f9895805edd20602f2d7f720186dfd906e82b4982e1"
  end

  if OS.mac?
    resource "zxing-cpp" do
      url "https://files.pythonhosted.org/packages/3d/46/ef7c69bea44a7c64d4a740679dd18c59616d610fb468c057d8bfbda5f063/zxing_cpp-2.3.0-cp313-cp313-macosx_10_13_universal2.whl"
      sha256 "3da0fbf0d93ef85663def561e8f7880447970710ea6b1768dfc05550a9ee3e00"
    end
  elsif Hardware::CPU.intel?
    resource "zxing-cpp" do
      url "https://files.pythonhosted.org/packages/ce/5e/5784ad14f8514e4321f3a828dccc00ebcf70202f6ef967174d26bcb65568/zxing_cpp-2.3.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
      sha256 "7ba641ca5a0f19b97d7bc6a0212e61dab267a2b1a52a84946d02bdcd859ec318"
    end
  else
    resource "zxing-cpp" do
      url "https://files.pythonhosted.org/packages/d9/f2/b781bf6119abe665069777e3c0f154752cf924fe8a55fca027243abbc555/zxing_cpp-2.3.0.tar.gz"
      sha256 "3babedb67a4c15c9de2c2b4c42d70af83a6c85780c1b2d9803ac64c6ae69f14e"
    end
  end

  def install
    venv = virtualenv_create(libexec, "python3.13")
    resources.each do |resource|
      resource.stage do
        wheel_file = Dir["*.whl"].first
        if wheel_file.nil?
          venv.pip_install Pathname.pwd
        else
          venv.pip_install Pathname.pwd/wheel_file
        end
      end
    end
    venv.pip_install_and_link buildpath
  end

  test do
    env "ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", "1"
    assert_match "Usage", shell_output("#{bin}/ethernity --help")
  end
end
