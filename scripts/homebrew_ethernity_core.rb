class Ethernity < Formula
  include Language::Python::Virtualenv

  desc "Secure, offline-recoverable backup system with QR-based recovery documents"
  homepage "https://github.com/MinorGlitch/ethernity"
  url "https://github.com/MinorGlitch/ethernity/archive/refs/tags/v0.2.1.tar.gz"
  sha256 "8f5e1848ca6c689287557a383cd787aea1cb440f7de45b7850d14b1c38fb34fb"
  license "GPL-3.0-or-later"

  depends_on "pkgconf" => :build
  depends_on "rust" => :build
  depends_on "certifi"
  depends_on "libxml2"
  depends_on "libxslt"
  depends_on "pillow"
  depends_on "python@3.13"

  resource "cbor2" do
    url "https://files.pythonhosted.org/packages/d9/8e/8b4fdde28e42ffcd741a37f4ffa9fb59cd4fe01625b544dfcfd9ccb54f01/cbor2-5.8.0.tar.gz"
    sha256 "b19c35fcae9688ac01ef75bad5db27300c2537eb4ee00ed07e05d8456a0d4931"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/3d/fa/656b739db8587d7b5dfa22e22ed02566950fbfbcdc20311993483657a5c0/click-8.3.1.tar.gz"
    sha256 "12ff4785d337a1bb490bb7e9c2b1ee5da3112e94a8622f26a6c77f5d2fc6842a"
  end

  resource "defusedxml" do
    url "https://files.pythonhosted.org/packages/0f/d5/c66da9b79e5bdb124974bfe172b4daf3c984ebd9c2a06e2b8a4dc7331c72/defusedxml-0.7.1.tar.gz"
    sha256 "1bb3032db185915b62d7c6209c5a8792be6a32ab2fedacc84e01b52c51aa3e69"
  end

  resource "fonttools" do
    url "https://files.pythonhosted.org/packages/ec/ca/cf17b88a8df95691275a3d77dc0a5ad9907f328ae53acbe6795da1b2f5ed/fonttools-4.61.1.tar.gz"
    sha256 "6675329885c44657f826ef01d9e4fb33b9158e9d93c537d84ad8399539bc6f69"
  end

  resource "fpdf2" do
    url "https://files.pythonhosted.org/packages/e9/c0/784b130a28f4ed612e9aff26d1118e1f91005713dcd0a35e60b54d316b56/fpdf2-2.8.5.tar.gz"
    sha256 "af4491ef2e0a5fe476f9d61362925658949c995f7e804438c0e81008f1550247"
  end

  resource "greenlet" do
    url "https://files.pythonhosted.org/packages/c7/e5/40dbda2736893e3e53d25838e0f19a2b417dfc122b9989c91918db30b5d3/greenlet-3.3.0.tar.gz"
    sha256 "a82bb225a4e9e4d653dd2fb7b8b2d36e4fb25bc0165422a11e48b88e9e6f78fb"
  end

  resource "jinja2" do
    url "https://files.pythonhosted.org/packages/df/bf/f7da0350254c0ed7c72f3e33cef02e048281fec7ecec5f032d4aac52226b/jinja2-3.1.6.tar.gz"
    sha256 "0137fb05990d35f1275a587e9aee6d56da821fc83491a0fb838183be43f66d6d"
  end

  resource "lxml" do
    url "https://files.pythonhosted.org/packages/aa/88/262177de60548e5a2bfc46ad28232c9e9cbde697bd94132aeb80364675cb/lxml-6.0.2.tar.gz"
    sha256 "cd79f3367bd74b317dda655dc8fcfa304d9eb6e4fb06b7168c5cf27f96e0cd62"
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/5b/f5/4ec618ed16cc4f8fb3b701563655a69816155e79e24a17b651541804721d/markdown_it_py-4.0.0.tar.gz"
    sha256 "cb0a2b4aa34f932c007117b194e945bd74e0ec24133ceb5bac59009cda1cb9f3"
  end

  resource "markupsafe" do
    url "https://files.pythonhosted.org/packages/7e/99/7690b6d4034fffd95959cbe0c02de8deb3098cc577c67bb6a24fe5d7caa7/markupsafe-3.0.3.tar.gz"
    sha256 "722695808f4b6457b320fdc131280796bdceb04ab50fe1795cd540799ebe1698"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/d6/54/cfe61301667036ec958cb99bd3efefba235e65cdeb9c84d24a8293ba1d90/mdurl-0.1.2.tar.gz"
    sha256 "bb413d29f5eea38f31dd4754dd7377d4465116fb207585f97bf925588687c1ba"
  end

  resource "mnemonic" do
    url "https://files.pythonhosted.org/packages/ff/77/e6232ed59fbd7b90208bb8d4f89ed5aabcf30a524bc2fb8f0dafbe8e7df9/mnemonic-0.21.tar.gz"
    sha256 "1fe496356820984f45559b1540c80ff10de448368929b9c60a2b55744cc88acf"
  end

  resource "platformdirs" do
    url "https://files.pythonhosted.org/packages/cf/86/0248f086a84f01b37aaec0fa567b397df1a119f73c16f6c7a9aac73ea309/platformdirs-4.5.1.tar.gz"
    sha256 "61d5cdcc6065745cdd94f0f878977f8de9437be93de97c1c12f853c9c0cdcbda"
  end

  resource "prompt-toolkit" do
    url "https://files.pythonhosted.org/packages/a1/96/06e01a7b38dce6fe1db213e061a4602dd6032a8a97ef6c1a862537732421/prompt_toolkit-3.0.52.tar.gz"
    sha256 "28cde192929c8e7321de85de1ddbe736f1375148b02f2e17edd840042b1be855"
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

  elsif Hardware::CPU.arm?
    resource "playwright" do
      url "https://files.pythonhosted.org/packages/83/d7/b72eb59dfbea0013a7f9731878df8c670f5f35318cedb010c8a30292c118/playwright-1.57.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.whl"
      sha256 "38a1bae6c0a07839cdeaddbc0756b3b2b85e476c07945f64ece08f1f956a86f1"
    end

  else
    resource "playwright" do
      url "https://files.pythonhosted.org/packages/56/61/3a803cb5ae0321715bfd5247ea871d25b32c8f372aeb70550a90c5f586df/playwright-1.57.0-py3-none-manylinux1_x86_64.whl"
      sha256 "284ed5a706b7c389a06caa431b2f0ba9ac4130113c3a779767dda758c2497bb1"
    end

  end

  resource "pyrage" do
    url "https://files.pythonhosted.org/packages/ee/e8/918161376594d69b294e920bd6444f1d9997e6e6dd2aca18e15f1ef72463/pyrage-1.3.0.tar.gz"
    sha256 "b283a2e3d688cbf68c707f57d93fdab3304ff57c7e2e6b710c0b4bc9096ad9da"
  end

  resource "pyee" do
    url "https://files.pythonhosted.org/packages/95/03/1fd98d5841cd7964a27d729ccf2199602fe05eb7a405c1462eb7277945ed/pyee-13.0.0.tar.gz"
    sha256 "b391e3c5a434d1f5118a25615001dbc8f669cf410ab67d04c4d4e07c55481c37"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/b0/77/a5b8c569bf593b0140bde72ea885a803b82086995367bf2037de0159d924/pygments-2.19.2.tar.gz"
    sha256 "636cb2477cec7f8952536970bc533bc43743542f70392ae026374600add5b887"
  end

  resource "pypdf" do
    url "https://files.pythonhosted.org/packages/4d/9b/db1056a54eda8cd44f9e5128e87e1142cb328295dad92bbec0d39f251641/pypdf-6.5.0.tar.gz"
    sha256 "9e78950906380ae4f2ce1d9039e9008098ba6366a4d9c7423c4bdbd6e6683404"
  end

  resource "python-docx" do
    url "https://files.pythonhosted.org/packages/a9/f7/eddfe33871520adab45aaa1a71f0402a2252050c14c7e3009446c8f4701c/python_docx-1.2.0.tar.gz"
    sha256 "7bc9d7b7d8a69c9c02ca09216118c86552704edc23bac179283f2e38f86220ce"
  end

  resource "questionary" do
    url "https://files.pythonhosted.org/packages/f6/45/eafb0bba0f9988f6a2520f9ca2df2c82ddfa8d67c95d6625452e97b204a5/questionary-2.1.1.tar.gz"
    sha256 "3d7e980292bb0107abaa79c68dd3eee3c561b83a0f89ae482860b181c8bd412d"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/fb/d2/8920e102050a0de7bfabeb4c4614a49248cf8d5d7a8d01885fbb24dc767a/rich-14.2.0.tar.gz"
    sha256 "73ff50c7c0c1c77c8243079283f4edb376f0f6442433aecb8ce7e6d0b92d1fe4"
  end

  resource "segno" do
    url "https://files.pythonhosted.org/packages/1c/2e/b396f750c53f570055bf5a9fc1ace09bed2dff013c73b7afec5702a581ba/segno-1.6.6.tar.gz"
    sha256 "e60933afc4b52137d323a4434c8340e0ce1e58cec71439e46680d4db188f11b3"
  end

  resource "shellingham" do
    url "https://files.pythonhosted.org/packages/58/15/8b3609fd3830ef7b27b655beb4b4e9c62313a4e8da8c676e142cc210d58e/shellingham-1.5.4.tar.gz"
    sha256 "8dbca0739d487e5bd35ab3ca4b36e11c4078f3a234bfce294b0a0291363404de"
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/85/30/ff9ede605e3bd086b4dd842499814e128500621f7951ca1e5ce84bbf61b1/typer-0.21.0.tar.gz"
    sha256 "c87c0d2b6eee3b49c5c64649ec92425492c14488096dfbc8a0c2799b2f6f9c53"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/72/94/1a15dd82efb362ac84269196e94cf00f187f7ed21c242792a923cdb1c61f/typing_extensions-4.15.0.tar.gz"
    sha256 "0cea48d173cc12fa28ecabc3b837ea3cf6f38c6d1136f85cbaaf598984861466"
  end

  resource "wcwidth" do
    url "https://files.pythonhosted.org/packages/24/30/6b0809f4510673dc723187aeaf24c7f5459922d01e2f794277a3dfb90345/wcwidth-0.2.14.tar.gz"
    sha256 "4d478375d31bc5395a3c55c40ccdf3354688364cd61c4f6adacaa9215d0b3605"
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
    wheel_resources, source_resources = resources.partition do |resource|
      resource.downloader.basename.to_s.end_with?(".whl")
    end
    venv.pip_install source_resources
    wheel_resources.each do |wheel_resource|
      wheel_resource.stage do
        wheel_file = Pathname.pwd/wheel_resource.downloader.basename
        venv.pip_install wheel_file
      end
    end
    venv.pip_install_and_link buildpath
  end

  test do
    env "ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", "1"
    assert_match "Usage", shell_output("#{bin}/ethernity --help")
  end
end
