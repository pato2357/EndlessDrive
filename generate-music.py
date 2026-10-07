#!/usr/bin/env python3
"""Generate lo-fi driving tracks for Endless Drive with Lyria (Gemini API), then refresh music/playlist.js.

The API key is read from the GEMINI_API_KEY environment variable, or from a line
GEMINI_API_KEY=... in a .env file next to this script.

  python generate-music.py --dry-run          # show what would be generated, no API calls
  python generate-music.py --count 32 --yes   # generate 32 songs
"""
import argparse
import base64
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
MUSIC = os.path.join(ROOT, 'music')
ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/interactions'
PRICE = {'lyria-3.5': 0.08, 'lyria-3-pro-preview': 0.08, 'lyria-3-clip-preview': 0.04}
AUDIO_EXT = ('.mp3', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.wav', '.flac', '.webm')

# Folder names match the time slots index.html picks from (morning 5-10, day 11-16, evening 17-19, night 20-4).
TIMES = {
    'morning': {
        'bpm': 80,
        'mood': 'Bright, fresh early-morning drive. Optimistic and gentle, like the first coffee of the day, soft sunlight through morning mist.',
        'words': ['朝もやの', '夜明けの', '朝焼けの', '珈琲と'],
    },
    'day': {
        'bpm': 82,
        'mood': 'Sunny afternoon cruise with the windows down. Easygoing, warm and groovy, carefree head-nodding feel.',
        'words': ['昼下がりの', '陽だまりの', '白い雲と', '午後の'],
    },
    'evening': {
        'bpm': 74,
        'mood': 'Driving into the sunset at golden hour. Bittersweet, nostalgic and gentle, warm orange light.',
        'words': ['夕焼けの', '黄昏の', '帰り道の', '茜色の'],
    },
    'night': {
        'bpm': 68,
        'mood': 'Late-night drive under the stars on an empty road. Dreamy, calm, introspective and a little sleepy.',
        'words': ['月明かりの', '星降る', '夜更けの', '真夜中の'],
    },
}
BIOMES = {
    'meadow':   {'flavor': 'Light acoustic guitar and a soft airy synth lead, breezy open green fields.', 'words': ['草原', 'そよ風', '風見鶏']},
    'forest':   {'flavor': 'Warm muted guitar and soft kalimba, earthy acoustic textures, cool pine-forest air.', 'words': ['松林', '木漏れ日', '森の匂い']},
    'autumn':   {'flavor': 'Mellow jazz guitar and warm Rhodes, cozy and slightly melancholic, falling maple leaves.', 'words': ['峠道', '落ち葉', '紅葉坂']},
    'sakura':   {'flavor': 'Subtle koto and Japanese pentatonic phrases over Rhodes, gentle spring breeze with cherry blossoms.', 'words': ['花びら', '春の窓', '桜並木']},
    'desert':   {'flavor': 'Warm slide guitar with wide reverb, open and spacious, a sunlit highway across a wide desert.', 'words': ['蜃気楼', '赤い大地', '砂の轍']},
    'snow':     {'flavor': 'Soft glockenspiel and celesta with airy pads, cold and sparkling winter air.', 'words': ['雪原', '白い吐息', '霧氷']},
    'coast':    {'flavor': 'Clean surf guitar or ukulele, relaxed ocean-breeze feel along a seaside road.', 'words': ['海風', '防波堤', '潮騒']},
    'lavender': {'flavor': 'Soft flute and nylon-string guitar, dreamy and floral, calm purple fields.', 'words': ['紫の丘', '風車', 'ラベンダー']},
    'bamboo':   {'flavor': 'Shakuhachi-like breathy flute and soft wooden percussion, quiet green bamboo grove.', 'words': ['竹林', '笹の葉', '竹の小径']},
    'paddy':    {'flavor': 'Gentle acoustic guitar and warm Rhodes, countryside rice fields, nostalgic Japanese summer.', 'words': ['田んぼ道', 'あぜ道', '稲穂']},
    'volcano':  {'flavor': 'Deep warm bass and slow, spacious pads, dark rocky landscape under a wide sky.', 'words': ['火の山', '溶岩台地', '黒い砂']},
    'jungle':   {'flavor': 'Marimba and soft hand percussion, lush humid rainforest after rain.', 'words': ['密林', '雨の森', 'スコール']},
    'savanna':  {'flavor': 'Warm kalimba and gentle shaker, golden grassland at a slow pace.', 'words': ['サバンナ', 'アカシア', '金色の草']},
    'lakeside': {'flavor': 'Clean electric guitar with soft reverb, calm lake surface and white birch trees.', 'words': ['湖畔', '白樺', '水面']},
    'sunflower': {'flavor': 'Bright ukulele and light whistle-like synth, sunny summer fields of sunflowers.', 'words': ['ひまわり', '夏の丘', '黄色い畑']},
    'town':     {'flavor': 'Mellow city-pop flavored Rhodes and muted guitar, a quiet old Japanese shopping street.', 'words': ['商店街', '路地裏', '自販機']},
}
VARIATIONS = [
    'Start with a short, soft intro before the beat comes in.',
    'Include a gentle electric piano solo in the middle section.',
    'Keep the arrangement sparse and spacious.',
    'Add a warm, round bassline that carries the groove.',
    'Let a soft melody return as a recurring motif.',
    'Use relaxed, swung drums with brushed snares.',
]

# Used once when the safety filter rejects the full prompt (it sometimes flags harmless words).
SIMPLE_PROMPT = 'Instrumental lo-fi chillhop, about {bpm} BPM, warm Rhodes chords, soft drums, mellow bass, {scene}. No vocals.'

PROMPT = """Instrumental lo-fi chillhop for a relaxing endless road trip. Instrumental only, no vocals, no singing, no lyrics.
Tempo around {bpm} BPM, laid-back swung drums with a soft kick and brushed snare, warm Rhodes electric piano playing jazzy 7th and 9th chords, round mellow bass.
Mood: {mood}
Scenery: {flavor}
{variation}
Clean, warm mix with only very subtle tape warmth. No vinyl crackle, no hiss, no noise.
Steady energy from start to finish so it works as continuous background music in a playlist."""


def load_key():
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    env = os.path.join(ROOT, '.env')
    if not key and os.path.exists(env):
        with open(env, encoding='utf-8-sig') as f:
            for line in f:
                name, _, value = line.strip().partition('=')
                if name.strip() == 'GEMINI_API_KEY':
                    key = value.strip().strip('"').strip("'")
    return key


# Hard limits on what we accept from the API. A 3-minute MP3 is about 5 MB (7 MB as base64) and a WAV
# about 32 MB, so anything far beyond these is treated as a broken or hostile response and nothing is written.
MAX_RESPONSE_BYTES = 96 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_ERROR_BYTES = 8 * 1024
MAX_JSON_DEPTH = 10
MAX_JSON_NODES = 20000
DIAG_CHARS = 4000


class Blocked(Exception):
    """The safety filter rejected the prompt (HTTP 400); nothing was generated or billed."""


class NotBilled(Exception):
    """The request was refused before any work was done (4xx, or rate limits that never cleared)."""


class Ambiguous(Exception):
    """The request may have reached the server and been processed; never resent automatically."""


def find_audio(res):
    """Return (base64 data, mime type) from an interactions response, searching at most
    MAX_JSON_DEPTH levels and MAX_JSON_NODES nodes."""
    stack, seen = [(res, 0)], 0
    while stack:
        obj, depth = stack.pop()
        seen += 1
        if seen > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise Ambiguous('response JSON is larger or deeper than expected; not saved')
        if isinstance(obj, dict):
            for k in ('output_audio', 'outputAudio'):
                a = obj.get(k)
                if isinstance(a, dict) and isinstance(a.get('data'), str):
                    return a['data'], a.get('mime_type') or a.get('mimeType')
            if obj.get('type') == 'audio' and isinstance(obj.get('data'), str):
                return obj['data'], obj.get('mime_type') or obj.get('mimeType')
            stack.extend((v, depth + 1) for v in obj.values() if isinstance(v, (dict, list)))
        elif isinstance(obj, list):
            stack.extend((v, depth + 1) for v in obj if isinstance(v, (dict, list)))
    return None


def decode_audio(data, mime, wav):
    if len(data) > MAX_AUDIO_BYTES * 4 // 3 + 4:
        raise RuntimeError('audio in the response is larger than expected; not saved')
    try:
        audio = base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        raise RuntimeError('audio in the response is not valid base64; not saved')
    if len(audio) > MAX_AUDIO_BYTES:
        raise RuntimeError('decoded audio is larger than expected; not saved')
    mime = mime or ('audio/wav' if wav else 'audio/mpeg')
    is_wav = audio[:4] == b'RIFF' and audio[8:12] == b'WAVE'
    is_mp3 = audio[:3] == b'ID3' or (len(audio) > 1 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0)
    if not (is_wav or is_mp3):
        raise RuntimeError('response did not contain MP3 or WAV audio; not saved')
    return audio, ('audio/wav' if is_wav else 'audio/mpeg')


def save_diagnostic(res):
    text = json.dumps(res, ensure_ascii=False)[:DIAG_CHARS]
    with open(os.path.join(MUSIC, 'last-response.json'), 'w', encoding='utf-8') as f:
        f.write(text)


def generate(key, model, prompt, wav):
    """One generation request. Only HTTP 429 (refused, nothing generated) is retried; a timeout,
    dropped connection or 5xx may already have produced (and billed) a song, so it is never resent."""
    body = {'model': model, 'input': prompt}
    if wav:
        body['response_format'] = {'type': 'audio'}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode('utf-8'), method='POST',
                                 headers={'x-goog-api-key': key, 'Content-Type': 'application/json'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                length = r.headers.get('Content-Length')
                if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                    raise Ambiguous('response is larger than expected; not read')
                raw = r.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise Ambiguous('response is larger than expected; not saved')
            try:
                res = json.loads(raw.decode('utf-8'))
            except (ValueError, RecursionError):
                raise Ambiguous('response was not valid JSON; not saved')
            found = find_audio(res)
            if not found:
                save_diagnostic(res)
                raise Ambiguous('no audio in response (first part saved to music/last-response.json)')
            return decode_audio(found[0], found[1], wav)
        except urllib.error.HTTPError as e:
            detail = e.read(MAX_ERROR_BYTES).decode('utf-8', 'replace')[:600]
            if e.code == 400 and ('prohibited_content' in detail or 'content_blocked' in detail):
                raise Blocked(detail)
            if e.code == 429 and ('limit: 0' in detail or 'Free Tier' in detail):
                raise NotBilled('this key is on the free tier, which has no Lyria quota. '
                                'Enable billing for the project at https://aistudio.google.com/ and run again.\n    ' + detail)
            if e.code == 429 and attempt < 4:
                wait = 20 * (attempt + 1)
                print(f'    HTTP 429 (rate limited, nothing generated), retrying in {wait}s ...')
                time.sleep(wait)
                continue
            if 400 <= e.code < 500:
                raise NotBilled(f'HTTP {e.code}: {detail}')
            raise Ambiguous(f'HTTP {e.code}: {detail}')
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise Ambiguous(f'network error ({e})')
    raise NotBilled('still rate limited after several tries')


def write_playlist():
    files = []
    for dirpath, _, names in os.walk(MUSIC):
        for n in names:
            if n.lower().endswith(AUDIO_EXT):
                files.append(os.path.relpath(os.path.join(dirpath, n), MUSIC).replace('\\', '/'))
    files.sort()
    lines = ''.join('  ' + json.dumps(f, ensure_ascii=False) + ',\n' for f in files)
    with open(os.path.join(MUSIC, 'playlist.js'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Generated by update-playlist.bat. Paths are relative to the music folder.\nwindow.PLAYLIST = [\n' + lines + '];\n')
    return len(files)


def plan(count, times, biomes, seed, done):
    rnd = random.Random(seed)
    combos = [(t, b) for t in times for b in biomes]
    jobs, used = [], set()
    for t in times:
        d = os.path.join(MUSIC, t)
        if os.path.isdir(d):
            used.update(os.path.splitext(n)[0] for n in os.listdir(d))
    i = 0
    while len(jobs) < count:
        if i % len(combos) == 0:
            rnd.shuffle(combos)
            combos.sort(key=lambda c: done.get(c, 0))   # fill the gaps first
        t, b = combos[i % len(combos)]
        i += 1
        titles = [w1 + w2 for w1 in TIMES[t]['words'] for w2 in BIOMES[b]['words']]
        rnd.shuffle(titles)
        title = next((x for x in titles if x not in used), None)
        if title is None:
            n = 2
            while f'{titles[0]} {n}' in used:
                n += 1
            title = f'{titles[0]} {n}'
        used.add(title)
        prompt = PROMPT.format(bpm=TIMES[t]['bpm'], mood=TIMES[t]['mood'], flavor=BIOMES[b]['flavor'], variation=rnd.choice(VARIATIONS))
        simple = SIMPLE_PROMPT.format(bpm=TIMES[t]['bpm'], scene=f'{t} drive, {b} scenery')
        jobs.append({'time': t, 'biome': b, 'title': title, 'prompt': prompt, 'simple': simple})
        done[(t, b)] = done.get((t, b), 0) + 1
        if i > count * 50:
            break
    return jobs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--count', type=int, default=32, help='number of songs to generate (default 32)')
    ap.add_argument('--model', default='lyria-3.5', help='lyria-3.5 (full songs) or lyria-3-clip-preview (30 s clips)')
    ap.add_argument('--times', default=','.join(TIMES), help='comma list of: ' + ','.join(TIMES))
    ap.add_argument('--biomes', default=','.join(BIOMES), help='comma list of: ' + ','.join(BIOMES))
    ap.add_argument('--wav', action='store_true', help='ask for WAV instead of MP3 (much larger files)')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--dry-run', action='store_true', help='print the plan without calling the API')
    ap.add_argument('--yes', action='store_true', help='skip the cost confirmation')
    a = ap.parse_args()
    times = [t for t in a.times.split(',') if t in TIMES]
    biomes = [b for b in a.biomes.split(',') if b in BIOMES]
    log_path = os.path.join(MUSIC, 'generated.json')
    log = json.load(open(log_path, encoding='utf-8')) if os.path.exists(log_path) else []
    done = {}
    for e in log:
        if os.path.exists(os.path.join(MUSIC, e['file'])):
            done[(e['time'], e['biome'])] = done.get((e['time'], e['biome']), 0) + 1
    jobs = plan(a.count, times, biomes, a.seed, done)
    cost = len(jobs) * PRICE.get(a.model, 0.08)
    print(f'{len(jobs)} songs with {a.model}  (about ${cost:.2f}; at most {len(jobs)} billable requests, failures are not resent)')
    for j in jobs:
        print(f"  {j['time']:<8} {j['biome']:<9} {j['title']}")
    if a.dry_run:
        print('\nExample prompt:\n' + jobs[0]['prompt'])
        return
    key = load_key()
    if not key:
        sys.exit('GEMINI_API_KEY was not found. Put GEMINI_API_KEY=... in .env next to this script.')
    if not a.yes and input(f'Generate these for about ${cost:.2f}? [y/N] ').strip().lower() != 'y':
        return
    # Requests that may be billed (successes and ambiguous failures) never exceed the number of songs
    # that was confirmed above, so the estimate is also the worst case.
    budget = len(jobs)
    billable = ok = fails = 0

    def request(prompt):
        nonlocal billable
        if billable >= budget:
            raise NotBilled(f'reached the limit of {budget} billable requests for this run')
        try:
            return generate(key, a.model, prompt, a.wav)
        except (Blocked, NotBilled):
            raise
        except Exception:
            billable += 1
            raise

    for n, j in enumerate(jobs, 1):
        print(f"[{n}/{len(jobs)}] {j['time']}/{j['title']} ...", flush=True)
        t0 = time.time()
        used_prompt = j['prompt']
        try:
            try:
                audio, mime = request(used_prompt)
            except Blocked:
                print('    the safety filter rejected the prompt; trying a shorter one')
                used_prompt = j['simple']
                try:
                    audio, mime = request(used_prompt)
                except Blocked:
                    print('    rejected again; skipping this song')
                    continue
            billable += 1
        except Ambiguous as e:
            print(f'    failed: {e}')
            print('    not resending: the server may already have made (and billed) this song')
            fails += 1
            if fails >= 2:
                print('    stopping after two uncertain failures in a row')
                break
            continue
        except Exception as e:
            print(f'    failed: {e}')
            print('    stopping so no more requests are spent on a problem that keeps happening')
            break
        fails = 0
        ext = '.wav' if 'wav' in mime else '.mp3'
        d = os.path.join(MUSIC, j['time'])
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, j['title'] + ext)
        with open(path, 'wb') as f:
            f.write(audio)
        ok += 1
        log.append({'file': os.path.relpath(path, MUSIC).replace('\\', '/'), 'model': a.model, 'time': j['time'],
                    'biome': j['biome'], 'prompt': used_prompt, 'created': time.strftime('%Y-%m-%d %H:%M:%S')})
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=1)
        total = write_playlist()
        print(f'    saved {len(audio) / 1e6:.1f} MB in {time.time() - t0:.0f}s  (playlist: {total} tracks)')
    print(f'\nDone: {ok}/{len(jobs)} songs. Reload index.html to hear them.')


if __name__ == '__main__':
    main()
