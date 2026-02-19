class Ethernity < Formula
  desc "Secure, offline-recoverable backup system with QR-based recovery documents"
  homepage "https://github.com/MinorGlitch/ethernity"
  license "GPL-3.0-or-later"
  version "0.2.1"

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/MinorGlitch/ethernity/releases/download/v0.2.1/ethernity-v0.2.1-macos-arm64.tar.gz"
      sha256 "c94c03e6e3324344317cd860ddc13e15e2288b7e9eae81fee187123d2c26410b"
    else
      url "https://github.com/MinorGlitch/ethernity/releases/download/v0.2.1/ethernity-v0.2.1-macos-x64.tar.gz"
      sha256 "a1cc66a2203681d02ff0b00970fd4ea11676189ebf4369f33755304b504224f1"
    end
  end

  on_linux do
    if Hardware::CPU.arm?
      url "https://github.com/MinorGlitch/ethernity/releases/download/v0.2.1/ethernity-v0.2.1-linux-arm64.tar.gz"
      sha256 "da4f73a89445c8c06f0e37e665a3b9da43ae73734e962d4bbaf6c2288084ec10"
    else
      url "https://github.com/MinorGlitch/ethernity/releases/download/v0.2.1/ethernity-v0.2.1-linux-x64.tar.gz"
      sha256 "7c1d6d376100c954041f7b7aecb35852f4715022bbebb76126ab265366c7e480"
    end
  end

  def install
    bundle_dir = Dir["ethernity-v#{version}-*"]&.first
    raise "Unable to locate extracted release bundle" if bundle_dir.nil?

    libexec.install Dir["#{bundle_dir}/*"]
    bin.install_symlink libexec/"ethernity"
  end

  test do
    env "ETHERNITY_SKIP_PLAYWRIGHT_INSTALL", "1"
    assert_match "Usage", shell_output("#{bin}/ethernity --help")
  end
end
