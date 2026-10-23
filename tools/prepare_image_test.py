#!/usr/bin/env python3
"""Prepare the synthetic image/sampler test offline; never invoke its harness."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

from image_probe_reference import contract
from prepare_lab_test import ICD_RELATIVE, ICD_TEMPLATE, REPO, regular_file, sha256


PROBE_FILES = (
    'probe_bmg.bin', 'disasm/.text.bridge_image_probe.asm',
    'embedded-probe.spvasm', 'payload-audit.json', 'probe-spec.json',
    'placeholder.spv', 'canary.spv', 'wg2_1_5.cmk',
)


def validate_probe(probe):
    """Recompute this probe's own audit and complete CMK packet, not the PRE's."""
    from build_image_probe import audit_image_payload, pack_image_probe

    for name in PROBE_FILES:
        regular_file(probe / name, name)
    spec = json.loads((probe / 'probe-spec.json').read_text())
    for key, value in contract().items():
        if spec.get(key) != value:
            raise ValueError(f'image probe contract mismatch: {key}')
    zebin = (probe / 'probe_bmg.bin').read_bytes()
    audit = audit_image_payload(zebin,
                                (probe / 'disasm/.text.bridge_image_probe.asm').read_text(),
                                (probe / 'embedded-probe.spvasm').read_text())
    if audit != json.loads((probe / 'payload-audit.json').read_text()):
        raise ValueError('Image payload audit differs from recomputed report')
    packet, _ = pack_image_probe(zebin, audit)
    if packet != (probe / 'wg2_1_5.cmk').read_bytes():
        raise ValueError('Image CMK3 differs from the complete audited packet')
    return spec, audit


def prepare(mesa_build, probe_dir, harness, output_root):
    mesa = Path(mesa_build).resolve()
    probe = Path(probe_dir).resolve()
    executable = regular_file(harness, 'image harness')
    library = regular_file(mesa / ICD_RELATIVE, 'local Mesa library')
    template_path = regular_file(mesa / ICD_TEMPLATE, 'local ICD template')
    spec, audit = validate_probe(probe)
    template = json.loads(template_path.read_text())
    version = template['ICD']['api_version']
    if template['file_format_version'] not in ('1.0.0', '1.0.1'):
        raise ValueError('Unsupported ICD format')
    import re
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid ICD API version')

    output = Path(output_root).absolute()
    output.mkdir(parents=True, exist_ok=False)
    icd = output / 'intel-local-icd.json'
    icd.write_text(json.dumps({
        'file_format_version': template['file_format_version'],
        'ICD': {'api_version': version, 'library_path': str(library)},
    }, indent=2) + '\n')
    paths = {'harness': executable, 'mesa_icd_library': library, 'icd_manifest': icd}
    paths.update({f'probe/{name}': regular_file(probe / name, name) for name in PROBE_FILES})
    paths['cpu_reference'] = regular_file(REPO / 'tools/image_probe_reference.py', 'CPU reference')
    manifest = {
        'schema_version': 1, 'status': 'prepared-manual-opt-in-not-gpu-validated',
        'kind': spec['kind'], 'gpu_executed': False, 'gpu_validated': False,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'roots': {'mesa_build': str(mesa), 'probe': str(probe), 'harness': str(executable)},
        'icd': {'manifest': str(icd), 'library_path': str(library), 'api_version': version},
        'files': {name: {'path': str(path.resolve()), 'sha256': sha256(path),
                         'size_bytes': path.stat().st_size} for name, path in sorted(paths.items())},
        'probe_audit_regenerated': True,
        'notice': 'Synthetic image/sampler test; not PRE or FSR. Manual GPU opt-in required.',
        'probe_audit_status': audit['status'],
    }
    manifest_path = output / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    launcher = output / 'run-manual.py'
    launcher.write_text('#!/usr/bin/env python3\nimport sys\n'
                        f'sys.path.insert(0, {str(REPO / "tools")!r})\n'
                        'import prepare_lab_test\n'
                        f'raise SystemExit(prepare_lab_test.launch_cli({str(manifest_path)!r}))\n')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesa-build', type=Path, default=REPO / 'build/mesa-26.1.2/out')
    parser.add_argument('--probe-dir', type=Path, required=True)
    parser.add_argument('--harness', type=Path, default=REPO / 'build/image-harness/image_probe')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    output = args.out or REPO / 'build' / ('image-test-' + datetime.now().strftime('%Y%m%d-%H%M%S')
                                         + '-' + uuid.uuid4().hex[:8])
    try:
        output = prepare(args.mesa_build, args.probe_dir, args.harness, output)
    except (OSError, ValueError, KeyError, ImportError, json.JSONDecodeError) as exc:
        print(f'blocked: {exc}', file=sys.stderr)
        return 2
    print(f'Prepared without GPU execution: {output}')
    print(f'Manual experiment only: python3 {output / "run-manual.py"} --run-gpu')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
