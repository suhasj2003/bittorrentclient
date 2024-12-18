num_pieces = 0
self_bitfield = []
pieces = []
piece_size = 0
block_size = 16384 # 16 kb
bencode_data = None
output_file = None
downloaded = 0
uploaded = 0
peer_sockets = []
connected_peers = {}
last_tracker_contact = None


total_size = 0
ip_address = None
port = None
url_info_hash = None
compact = False
parsed_url = None
peer_id = None
init_num_peers = 0

verbose = False
pieces_complete = 0
