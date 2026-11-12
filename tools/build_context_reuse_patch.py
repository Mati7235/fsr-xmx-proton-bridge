#!/usr/bin/env python3
"""Build the context-reuse candidate on top of the context-output candidate.

Pinned upstream source: ef39559d26e083ce1bd1353b2e8c86f33c3c264c (SHA-256 below).
Does NOT modify the upstream checkout. Output applies with `patch -p1` AFTER
patches/0002-shim-context-output.patch (stack order 0002 -> 0003).

Reuse problem: both legacy D3D12 exports (and Context2) return early S_OK when
the supplied context already carries a D3D12 half, without validating the new
caller or copying any outputs into its fresh structure.

Reuse contract implemented here, per legacy/D3D12 function:
  1. Device identity: the stored half's m_pAppDevice must equal pDevice,
     else E_INVALIDARG (never rebind a live half, never touch outputs).
  2. Version: the requested version must be supported by the GRANTED version
     stored at init (INTCExtensionVersionHelper::IsSupported), else
     E_NOINTERFACE (same code InitExtensions uses for unsupported versions).
  3. Refresh: re-run InitExtensions on the live half into a zeroed temp
     (same device, so the rebind is a no-op) and copy the outputs back with
     the 0002 helper (legacy) or full-struct assignment (Context2). The
     granted version is saved/restored so a lower requested version cannot
     silently downgrade the live contract. Any failure leaves the caller
     structure untouched.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
from pathlib import Path

import build_context_output_patch as output_patch

RELATIVE = output_patch.RELATIVE
SOURCE_SHA256 = output_patch.SOURCE_SHA256


def once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"expected one source anchor, found {text.count(old)}: {old[:70]!r}")
    return text.replace(old, new, 1)


REUSE_ELSE_LEGACY = """    else
    {
        // Reused D3D12 half: never rebind a live context. Validate the caller
        // against the granted contract, then refresh the outputs deterministically.
        D3D12ExtensionContext* const liveHalf = pExtensionContext->m_pD3D12ExtensionContext;
        if (liveHalf->m_pAppDevice.Get() != pDevice)
        {
            return E_INVALIDARG;
        }
        INTCExtensionVersionHelper grantedVersion(liveHalf->m_SupportedExtVersion);
        if (!grantedVersion.IsSupported(pExtensionInfo->RequestedExtensionVersion))
        {
            return E_NOINTERFACE;
        }
        const INTCExtensionVersion agreedVersion = liveHalf->m_SupportedExtVersion;
        INTCExtensionInfo1 reuseInfo1;
        memset(&reuseInfo1, 0, sizeof(INTCExtensionInfo1));
        reuseInfo1.RequestedExtensionVersion = pExtensionInfo->RequestedExtensionVersion;
        if (FAILED(result = liveHalf->InitExtensions(pDevice, nullptr, 0, &reuseInfo1, %s)))
        {
            liveHalf->m_SupportedExtVersion = agreedVersion;
            return result;
        }
        liveHalf->m_SupportedExtVersion = agreedVersion;
        CopyExtensionInfo1OutputsToOld(*pExtensionInfo, reuseInfo1);
        return S_OK;
    }
"""

REUSE_ELSE_CONTEXT2 = """    else
    {
        // Reused D3D12 half: never rebind a live context. Validate the caller
        // against the granted contract, then refresh the full-width outputs.
        D3D12ExtensionContext* const liveHalf = pExtensionContext->m_pD3D12ExtensionContext;
        if (liveHalf->m_pAppDevice.Get() != pDevice)
        {
            return E_INVALIDARG;
        }
        INTCExtensionVersionHelper grantedVersion(liveHalf->m_SupportedExtVersion);
        if (!grantedVersion.IsSupported(pExtensionInfo->RequestedExtensionVersion))
        {
            return E_NOINTERFACE;
        }
        const INTCExtensionVersion agreedVersion = liveHalf->m_SupportedExtVersion;
        INTCExtensionInfo1 reuseInfo1;
        memset(&reuseInfo1, 0, sizeof(INTCExtensionInfo1));
        reuseInfo1.RequestedExtensionVersion = pExtensionInfo->RequestedExtensionVersion;
        if (FAILED(result = liveHalf->InitExtensions(pDevice, nullptr, 0, &reuseInfo1, pExtensionAppInfo)))
        {
            liveHalf->m_SupportedExtVersion = agreedVersion;
            return result;
        }
        liveHalf->m_SupportedExtVersion = agreedVersion;
        *pExtensionInfo = reuseInfo1;
        return S_OK;
    }
"""

OLD_ELSE = """    else
    {
        // We already seem to have a context
        return S_OK;
    }
"""


def reuse_body(source: str, name: str, appinfo: str, context2: bool = False) -> str:
    start = source.index("HRESULT " + name)
    end = source.index("\n}\n", start)
    body = source[start:end]
    replacement = REUSE_ELSE_CONTEXT2 if context2 else REUSE_ELSE_LEGACY % appinfo
    body = once(body, OLD_ELSE, replacement)
    return source[:start] + body + source[end:]


def build_full(source: str) -> str:
    """Pristine source -> 0002 output -> 0003 output (stacked)."""
    after_output = output_patch.build(source)
    after_reuse = reuse_body(after_output,
                             "_INTC_D3D12_CreateDeviceExtensionContext(",
                             "&extensionAppInfo")
    after_reuse = reuse_body(after_reuse,
                             "_INTC_D3D12_CreateDeviceExtensionContext1(",
                             "pExtensionAppInfo")
    after_reuse = reuse_body(after_reuse,
                             "_INTC_D3D12_CreateDeviceExtensionContext2(",
                             "pExtensionAppInfo", context2=True)
    return after_reuse


def build(source: str) -> str:
    """0002-applied source -> 0003 output (single stacked layer for the patch)."""
    return reuse_body(
        reuse_body(
            reuse_body(source,
                       "_INTC_D3D12_CreateDeviceExtensionContext(",
                       "&extensionAppInfo"),
            "_INTC_D3D12_CreateDeviceExtensionContext1(",
            "pExtensionAppInfo"),
        "_INTC_D3D12_CreateDeviceExtensionContext2(",
        "pExtensionAppInfo", context2=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=output_patch.ROOT / "upstream/xess-xmx-linux" / RELATIVE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = args.source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"refusing unpinned source: SHA-256 {digest}; expected {SOURCE_SHA256}")
    before_patched = output_patch.build(data.decode("utf-8"))
    after = build(before_patched)
    patch = "".join(difflib.unified_diff(before_patched.splitlines(True), after.splitlines(True),
                                         fromfile="a/" + RELATIVE.as_posix(),
                                         tofile="b/" + RELATIVE.as_posix()))
    if args.output:
        with args.output.open("x") as stream:
            stream.write(patch)
    else:
        print(patch, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
