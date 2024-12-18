import random
import urllib
import socket
import time

import config
def contact_tracker():
   # Set starting vals for data received, which is none
    # Generate peer id using Azureus-style GT means Great Torrent :)
    config.peer_id = b"-GT0001-"
    config.peer_id += bytes([random.randint(0, 255) for _ in range(20 - len(config.peer_id))])
    url_peer_id = urllib.parse.quote(config.peer_id)
    uploaded = str(config.uploaded)
    downloaded = str(config.downloaded)
    left = str(config.total_size - config.downloaded)
    
    # Form GET request
    # Credit: https://www.internalpointers.com/post/making-http-requests-sockets-python
    get_request = "GET /announce" + \
                "?info_hash=" + config.url_info_hash + \
                "&peer_id=" + url_peer_id + \
                "&ip=" + config.ip_address + \
                "&port=" + str(config.port) + \
                "&uploaded=" + uploaded + \
                "&downloaded=" + downloaded + \
                "&left=" + str(left)
    
    if config.compact:
        get_request += "&compact=1"
    
    get_request += "&event=started HTTP/1.1\r\n" + \
                   "Host: " + config.parsed_url.hostname + "\r\n\r\n"
    if config.verbose: print(f"(parse) GET request:\n{get_request}")

    
    # Establish connection to tracker 
    tracker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tracker_socket.connect((config.parsed_url.hostname, config.parsed_url.port))
    
    # Send GET Request
    tracker_socket.send(get_request.encode())
    
    # Receive response from tracker
    response = b""
    while True:
        data = tracker_socket.recv(4096)
        if not data:
            break
        response += data
    
    # Close connection to tracker
    tracker_socket.close()
    config.last_tracker_contact = time.time()
    return response
