"""Install pinned dependencies and restore external resources; binaries stay ignored."""
from pathlib import Path
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, tempfile, time, urllib.request, zipfile
ROOT=Path(__file__).resolve().parent

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def download(item):
    target=ROOT/item['path']
    if target.is_file() and digest(target)==item['sha256']:
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    pending=target.with_name(target.name+'.part')
    for attempt in range(3):
        try:
            print('Downloading '+item['path'],flush=True)
            request=urllib.request.Request(item['url'],headers={'User-Agent':'PersonalToolSetup/1.0'})
            with urllib.request.urlopen(request,timeout=120) as source,pending.open('wb') as output:
                shutil.copyfileobj(source,output,1024*1024)
            if digest(pending)!=item['sha256']:
                raise RuntimeError('Checksum mismatch: '+item['path'])
            os.replace(pending,target)
            if item.get('executable') and os.name!='nt':
                target.chmod(0o755)
            return
        except Exception:
            pending.unlink(missing_ok=True)
            if attempt==2:raise
            time.sleep(2*(attempt+1))

def selected(item):
    return item.get('platform',sys.platform)==sys.platform and item.get('arch',platform.machine().lower())==platform.machine().lower()

def resources(check=False,include_optional=False):
    manifest=ROOT/'resources.json'
    items=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    missing=[]
    for item in items:
        if not selected(item) or (item.get('optional') and not include_optional):continue
        if check:
            path=ROOT/item['path']
            if not path.is_file() or digest(path)!=item['sha256']:missing.append(item['path'])
        else:download(item)
    if missing:raise RuntimeError('Missing or changed resources: '+', '.join(missing))
    for item in items:
        if not selected(item) or not item.get('zip_members') or (item.get('optional') and not include_optional):continue
        if check:
            for dest in item['zip_members'].values():
                if not (ROOT/dest).is_file():raise RuntimeError('Missing extracted resource: '+dest)
            continue
        with zipfile.ZipFile(ROOT/item['path']) as archive:
            for suffix,dest in item['zip_members'].items():
                matches=[n for n in archive.namelist() if n.endswith('/'+suffix) or n==suffix]
                if len(matches)!=1:raise RuntimeError('Archive member not unique: '+suffix)
                target=ROOT/dest;target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(matches[0]) as source,target.open('wb') as output:shutil.copyfileobj(source,output)

def pip(*args):
    subprocess.run([sys.executable,'-m','pip','--disable-pip-version-check',*args],cwd=ROOT,check=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Verify required downloaded files without changing anything')
    parser.add_argument('--resources-only',action='store_true')
    parser.add_argument('--skip-models',action='store_true',help='Install dependencies only; rerun setup before use')
    parser.add_argument('--include-optional',action='store_true')
    args=parser.parse_args()
    os.chdir(ROOT)
    if args.check:
        resources(check=True,include_optional=args.include_optional);print('Resource checks passed.');return
    if not args.resources_only:
        (ROOT/'.setup-complete').unlink(missing_ok=True)
        if sys.version_info[:2]!=(3,11):raise RuntimeError('Use Python 3.11 for these pinned dependencies.')
        native=ROOT/('requirements-windows.txt' if os.name=='nt' else 'requirements-mac.txt')
        if native.exists():pip('install','-r',native.name)
        lock=ROOT/('requirements-lock-windows.txt' if os.name=='nt' else 'requirements.txt')
        pip('install','-r',lock.name)
        if (ROOT/'vendor/OmniVoice/pyproject.toml').exists():
            pip('install','--no-deps','--no-build-isolation','-e','vendor/OmniVoice')
        if os.name=='nt' and (ROOT/'requirements-gpu.txt').exists() and shutil.which('nvidia-smi'):
            pip('install','-r','requirements-gpu.txt')
    if not args.skip_models:
        resources(include_optional=args.include_optional)
        envfile=ROOT/'.env'
        if not envfile.exists():shutil.copyfile(ROOT/'.env.example',envfile)
        # Download current public route/stop references; no API key is needed.
        subprocess.run([sys.executable,'pipeline.py','load-gtfs'],check=True)
        subprocess.run([sys.executable,'pipeline.py','build'],check=True)
    if not args.skip_models and not args.resources_only:
        (ROOT/'.setup-complete').write_text('Dependencies and resources restored.\n')
    print('Ready. Use Start.cmd on Windows or Start.command on Mac.')

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Setup failed: '+str(error),file=sys.stderr);sys.exit(1)
