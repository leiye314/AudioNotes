"""Export an explicit reviewed file list to a NEW local folder; never use Git."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'recordings', '阅读成品', 'outputs', 'work', 'eval', 'reports',
             'models', 'envs', 'tools', '.git', '.codex', '.agents'}
PRIVATE = {'profiles/local_settings.json', 'profiles/meeting_people.json',
           'profiles/research_meeting.json', 'profiles/logic_lecture.json'}


def safe_path(root, relative):
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('Expected a relative POSIX file path')
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith('/') or any(p in {'.', '..'} for p in parts):
        raise ValueError('Unsafe relative path')
    if parts[0].casefold() in FORBIDDEN or relative.casefold() in PRIVATE:
        raise ValueError('Private path is forbidden')
    path = root.joinpath(*parts)
    for part in [path, *path.parents]:
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Links and junctions cannot be exported')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes export root')
    return path


def scan_text(text):
    patterns = [r'(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|file:' + '/' * 2 + r'|/(?:Users|home)/|\\\\[\w.-]+\\)',
                r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b',
                r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----']
    if any(re.search(pattern, text) for pattern in patterns):
        raise ValueError('Machine path or credential-like text; review before export')


def prepare(root, manifest=None):
    manifest = manifest or root / 'release/public_allowlist.json'
    config = json.loads(manifest.read_text(encoding='utf-8'))
    result = {}; folded = set()
    for row in config['files']:
        source = safe_path(root, row['source'])
        safe_path(root, row['target'])
        key = row['target'].casefold()
        if key in folded or key == 'export_manifest.json':
            raise ValueError('Duplicate/reserved export target')
        folded.add(key)
        if source.suffix not in {'.py', '.md', '.json', '.ps1', '.txt'} and source.name not in {'.gitignore', 'LICENSE'}:
            raise ValueError('Unexpected file type')
        data = source.read_bytes()
        if row.get('transform') == 'policy_evidence':
            policy = json.loads(data)
            policy['evidence'] = 'docs/AUDIO_WORKFLOW.md'
            data = (json.dumps(policy, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        elif row.get('transform') == 'standalone_allowlist':
            exported = {'version': config['version'], 'files': [
                {'source': item['target'], 'target': item['target']} for item in config['files']]}
            data = (json.dumps(exported, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        elif row.get('transform'):
            raise ValueError('Unknown transformation')
        # Rules and synthetic tests contain scanner patterns, not personal values.
        # Test/example strings use concatenation for synthetic forbidden values.
        try:
            scan_text(data.decode('utf-8-sig'))
        except ValueError as exc:
            raise ValueError(f'{row["source"]}: {exc}') from exc
        result[row['target']] = data
    return result


def export(root, destination):
    files = prepare(root)
    destination = Path(destination).absolute()
    if destination.exists():
        raise FileExistsError('Destination must not exist; exports never overwrite')
    # Refuse aliases in the destination ancestry as well.
    for part in destination.parents:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Destination ancestry contains a link or junction')
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for relative, data in files.items():
        path = safe_path(destination, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        if manifest[relative] != hashlib.sha256(data).hexdigest():
            raise RuntimeError('Export readback mismatch')
    (destination / 'EXPORT_MANIFEST.json').write_text(
        json.dumps({'files': manifest, 'scope': 'local public candidate; no personal evidence'}, indent=2),
        encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--check', action='store_true')
    choice.add_argument('--destination', type=Path)
    args = parser.parse_args()
    files = prepare(ROOT) if args.check else export(ROOT, args.destination)
    print(json.dumps({'status': 'PASS', 'files': len(files), 'copied': not args.check}))


if __name__ == '__main__':
    main()
