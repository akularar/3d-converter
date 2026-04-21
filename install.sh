#!/usr/bin/env bash
set -euo pipefail

# 3d-converter prerequisite installer
# Installs Blender and gltfpack on Ubuntu/Debian Linux.
# Run: bash install.sh

echo "=== 3d-converter: Installing prerequisites ==="
echo ""

# ---------------------------------------------------------------------------
# Detect OS
# ---------------------------------------------------------------------------
if [[ ! -f /etc/os-release ]]; then
    echo "ERROR: Only Linux (Ubuntu/Debian) is supported by this script."
    echo "For macOS, install Blender from https://www.blender.org/download/"
    echo "and gltfpack from https://github.com/zeux/meshoptimizer/releases"
    exit 1
fi
. /etc/os-release

# ---------------------------------------------------------------------------
# Blender
# ---------------------------------------------------------------------------
BLENDER_VERSION="5.1.1"
BLENDER_URL="https://mirrors.ocf.berkeley.edu/blender/release/Blender5.1/blender-${BLENDER_VERSION}-linux-x64.tar.xz"
BLENDER_INSTALL_DIR="/opt/blender"

install_blender() {
    if command -v blender &>/dev/null; then
        CURRENT=$(blender --version 2>/dev/null | head -1 | grep -oP '[\d.]+' || echo "unknown")
        echo "[blender] Already installed: Blender ${CURRENT}"
        read -p "  Reinstall Blender ${BLENDER_VERSION}? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "[blender] Keeping existing installation."
            return
        fi
    fi

    echo "[blender] Installing Blender ${BLENDER_VERSION}..."
    TMPDIR=$(mktemp -d)
    TARBALL="${TMPDIR}/blender.tar.xz"

    echo "[blender] Downloading from ${BLENDER_URL}..."
    curl -L --progress-bar -o "${TARBALL}" "${BLENDER_URL}"

    echo "[blender] Extracting to ${BLENDER_INSTALL_DIR}..."
    sudo rm -rf "${BLENDER_INSTALL_DIR}"
    sudo mkdir -p "${BLENDER_INSTALL_DIR}"
    sudo tar -xf "${TARBALL}" -C "${BLENDER_INSTALL_DIR}" --strip-components=1

    # Symlink to PATH
    sudo ln -sf "${BLENDER_INSTALL_DIR}/blender" /usr/local/bin/blender

    rm -rf "${TMPDIR}"
    echo "[blender] Installed: $(blender --version 2>/dev/null | head -1)"
}

# ---------------------------------------------------------------------------
# gltfpack (from meshoptimizer releases)
# ---------------------------------------------------------------------------
GLTFPACK_VERSION="0.22"
GLTFPACK_URL="https://github.com/zeux/meshoptimizer/releases/download/v${GLTFPACK_VERSION}/gltfpack-${GLTFPACK_VERSION}-linux.zip"

install_gltfpack() {
    if command -v gltfpack &>/dev/null; then
        echo "[gltfpack] Already installed: $(gltfpack --version 2>&1 | head -1 || echo 'unknown version')"
        read -p "  Reinstall gltfpack ${GLTFPACK_VERSION}? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "[gltfpack] Keeping existing installation."
            return
        fi
    fi

    echo "[gltfpack] Installing gltfpack ${GLTFPACK_VERSION}..."
    TMPDIR=$(mktemp -d)

    # Try native binary first (includes BasisU support for KTX2)
    echo "[gltfpack] Downloading from ${GLTFPACK_URL}..."
    if curl -L --progress-bar -o "${TMPDIR}/gltfpack.zip" "${GLTFPACK_URL}" 2>/dev/null; then
        # Install unzip if needed
        if ! command -v unzip &>/dev/null; then
            echo "[gltfpack] Installing unzip..."
            sudo apt-get update -qq && sudo apt-get install -y -qq unzip
        fi
        unzip -o "${TMPDIR}/gltfpack.zip" -d "${TMPDIR}/"
        sudo install -m 755 "${TMPDIR}/gltfpack" /usr/local/bin/gltfpack
    else
        echo "[gltfpack] Native binary download failed, trying npm..."
        if command -v npm &>/dev/null; then
            sudo npm install -g gltfpack
        else
            echo "WARNING: Neither native binary nor npm available for gltfpack."
            echo "  Install Node.js and run: npm install -g gltfpack"
            echo "  Or download from: https://github.com/zeux/meshoptimizer/releases"
            rm -rf "${TMPDIR}"
            return
        fi
    fi

    rm -rf "${TMPDIR}"
    echo "[gltfpack] Installed: $(gltfpack 2>&1 | head -1 || echo 'ok')"
}

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
install_system_deps() {
    echo "[system] Checking system dependencies..."

    # Blender needs these for headless rendering
    DEPS="libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 libxi6 libxkbcommon0"
    MISSING=""
    for pkg in $DEPS; do
        if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
            MISSING="${MISSING} ${pkg}"
        fi
    done

    if [[ -n "$MISSING" ]]; then
        echo "[system] Installing missing packages:${MISSING}"
        sudo apt-get update -qq
        sudo apt-get install -y -qq ${MISSING}
    else
        echo "[system] All system dependencies present."
    fi
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
install_system_deps
echo ""
install_blender
echo ""
install_gltfpack

echo ""
echo "=== Installation complete ==="
echo ""
echo "Verify:"
echo "  blender --version"
echo "  gltfpack 2>&1 | head -1"
echo ""
echo "Usage:"
echo "  python convert.py model.fbx -o output/"
echo "  python convert.py model.obj -o output/ --compress meshopt"
