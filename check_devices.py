import json
try:
    import sounddevice as sd
except Exception as e:
    print('ERROR importing sounddevice:', e)
    raise SystemExit(1)

devices = sd.query_devices()

print('INPUT_DEVICES:')
for i, d in enumerate(devices):
    if int(d.get('max_input_channels', 0) or 0) > 0:
        print(f"{i}: {d.get('name')}")

print('\nREACHY_LIKE_INPUT_DEVICES:')
needles = ['reachy', 'reachy mini', 'pollen', 'respeaker', 'seeed', 'voicecard', 'ac108', 'mini audio']
found = []
for i, d in enumerate(devices):
    if int(d.get('max_input_channels', 0) or 0) <= 0:
        continue
    name = str(d.get('name', '"\'\'"'))
    low = name.lower()
    if any(n in low for n in needles):
        found.append((i, name))

if found:
    for i, name in found:
        print(f"{i}: {name}")
else:
    print('(none found)')

print('\nOUTPUT_DEVICES:')
for i, d in enumerate(devices):
    if int(d.get('max_output_channels', 0) or 0) > 0:
        print(f"{i}: {d.get('name')}")

print('\nREACHY_LIKE_OUTPUT_DEVICES:')
found = []
for i, d in enumerate(devices):
    if int(d.get('max_output_channels', 0) or 0) <= 0:
        continue
    name = str(d.get('name', '"\'\'"'))
    low = name.lower()
    if any(n in low for n in needles):
        found.append((i, name))

if found:
    for i, name in found:
        print(f"{i}: {name}")
else:
    print('(none found)')