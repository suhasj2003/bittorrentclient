from subtl import UdpTrackerClient

utc = UdpTrackerClient('udp://tracker.opentrackr.org', 1337)
utc.connect()
if not utc.poll_once():
    raise Exception('Could not connect')
print('Success!')

utc.announce(info_hash='089184ED52AA37F71801391C451C5D5ADD0D9501')
data = utc.poll_once()
if not data:
    raise Exception('Could not announce')
for a in data['response']['peers']:
    print(a)