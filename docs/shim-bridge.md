# Shim bridge

`igdext64.dll` stands in for the Intel driver components that nitec's FSR 4 mod queries. The mod resolves the DLL at start and calls its INTC D3D12 exports; the shim answers as an Intel Arc B580 and hands back a device context the mod can create pipelines on. The driver half of the bridge is the patched ANV described in [how-it-works.md](how-it-works.md).

## What the shim answers

The mod asks for version 4.20.0 and passes `INTCExtensionInfo` (192 bytes in the 64-bit Windows ABI). `shim/src/dll/IgdextApiDll.cpp` adapts it to `INTCExtensionInfo1` (200 bytes) and calls `D3D12ExtensionContext::InitExtensions`, which fills the device information and three driver outputs. `...Context1` takes the same path, and `...Context2` already receives the wider structure. `CheckFeatureSupport` answers from the detected GPU with the profile overrides. `_INTC_D3D12_GetCachedBlob` returns `E_NOTIMPL`, so the mod only loses a diagnostic PRE dump.

## Why 0002 exists: the outputs were not copied back

Both legacy exports adapted the requested version, called `InitExtensions` and returned without copying the result, so a caller got its input structure back unchanged and the device name, generation and driver outputs stayed empty.

`patches/0002-shim-context-output.patch` writes seven device-info fields, including the fixed-size generation-name array, and the three driver outputs one by one. It never copies the extended structure wholesale or exposes its GMD-only tail. Copy-back runs only after successful initialization and leaves the outputs untouched on failure; D3D11 and `...Context2` are out of scope. Upstream `8f45d12` copied the same fields inline, so at our pin of `662dc6e` the patch only moves them into the shared `CopyExtensionInfo1OutputsToOld` helper that 0003 reuses.

## Why 0003 exists: a reused context returned S_OK with zeroes

After 0002, the three D3D12 functions still returned early with `S_OK` when the supplied context already had a D3D12 half (`else { // We already seem to have a context return S_OK; }`), so reuse reported success with a zeroed output structure.

`patches/0003-shim-context-reuse.patch` applies this contract per function:

1. Device identity. The stored `m_pAppDevice` must equal `pDevice`, otherwise `E_INVALIDARG`. A live half is never rebound and the caller's outputs stay untouched.
2. Requested version. `INTCExtensionVersionHelper::IsSupported` must accept it against the granted version, otherwise `E_NOINTERFACE`. A lower request succeeds; a higher one fails instead of silently upgrading the half.
3. Refresh. `InitExtensions` re-runs on the live half into a zeroed temporary with the same device, and the outputs come back. The granted version is saved and restored around the refresh, and a failed refresh returns its error with caller and half intact.

The patch touches only `IgdextApiDll.cpp` and re-derives the outputs instead of caching them. Compatible reuse now fills the outputs, incompatible reuse fails, and a caller that relied on the silent path must handle the new errors. D3D11 halves keep the early return and write into the caller struct directly.

## Pins

| Item | Value |
|---|---|
| 4.1.2 source DLL | `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`, 45,558,272 B |
| Registry entry | code `68b962b5…`, input `ce372719…`, zebin `b1781bb4…`, profile `profiles/fsr4-pre-412-native1080-bmg.json` |
| PRE layout | base 4, push 52, 11 surfaces with BTIs `[8,9,1,2,3,4,5,6,7,10,11]`, sampler at 48 in a separate heap |
| Packs | 6 packs, 1,977 CM envelopes, 40102 carries the Xe2 PRE |

## Limits

`tests/test_context_output.py` and `tests/test_context_reuse.py` compile the patched bodies for Windows and run host executables; the stubs model the initializer, so upstream `D3D12ExtensionContext` does not run. No check loads the DLL in Wine, injects a kernel or reads pixels back. `S_OK`, a green build or the absence of a fail-stop does not prove the bridge works.
