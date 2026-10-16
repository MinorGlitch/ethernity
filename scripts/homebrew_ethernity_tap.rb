class Ethernity < Formula
  include Language::Python::Virtualenv

  desc "Secure, offline-recoverable backup system with QR-based recovery documents"
  homepage "https://github.com/MinorGlitch/ethernity"
  url "https://github.com/MinorGlitch/ethernity/archive/refs/tags/v0.9.1.tar.gz"
  sha256 "9efc1b94b7c8736505359143dee5ffa0e4b641fadcbdc2d8f5a96c13d97457c5"
  license "GPL-3.0-or-later"

  depends_on "pkgconf" => :build
  depends_on "rust" => :build
  depends_on "python@3.13"

  # @locked-python-resources@

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
    smoke_dir = buildpath/"tests/fixtures/v1_2/extension_golden/base64/gzip_replacement_chain/chain"
    smoke_root = smoke_dir/"qr_document.pdf"
    smoke_extension = Dir[smoke_dir/"extensions/01/qr_document-01-*.pdf"].first
    odie "missing extension smoke fixture" if smoke_extension.nil?
    (pkgshare/"smoke").install smoke_root => "extension-root.pdf"
    (pkgshare/"smoke").install smoke_extension => "extension-01.pdf"
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
