import random
import socket
import urllib.parse
import bencodepy # type: ignore
import hashlib
import argparse
import select
import time
import sys
import os

import config # Global variables
from comm import recv_handshake, recv_message, keep_alives, send_bitfield, remove_peer # Communication / protocol processing functions
from structs import Peer, Piece # Peer & Piece class
from tracker import contact_tracker

KEEP_ALIVE_TIMEOUT = 120
SELECT_TIMEOUT = 60.0
MAX_PEERS = 50

def add_new_peers():
    response = contact_tracker()
    # Seperate http get response header and body depending on server implementation
    carriage_return = True
    body_index = response.find(b'\r\n\r\n')
    if body_index == -1:
        body_index = response.find(b'\n\n')
        carriage_return = False

    # If no seperator found error and just exit
    if body_index == -1:
        print("Error: tracker response does not have body/header seperator")
        return

    # Split the header and body
    header = response[:body_index]
    body_index = body_index + 4 if carriage_return else body_index + 2
    body = response[body_index:]
    body_data = bencodepy.decode(body)
    
    # Get peers
    peers = body_data[b'peers']
    
    if config.verbose: print("Num Peers:")
    if config.compact:
        num_peers = len(peers)//6
    else:
        num_peers = len(peers)
    if config.verbose: print("Peer Info:")
    if config.verbose: print(peers)
    
    # Get interval we can request tracker
    interval = body_data.get(b'interval', 0)
    
    if config.verbose: print(f"Interval: {interval}")

    ## Test peer protocol
    # Construct handshake request
    pstrlen = 19
    reserved = 0
    handshake_request = pstrlen.to_bytes(1, 'big') + bytes("BitTorrent protocol", 'utf-8') + \
                        reserved.to_bytes(8, 'big') + \
                        config.info_hash + \
                        config.peer_id

    for i in range(num_peers): 
        if len(config.connected_peers) > MAX_PEERS:
            if config.verbose: print("Reached max threshold for peers, not creating any new ones") 
        if config.compact:
            peer = peers[:6]
            peers = peers[6:]
            
            peer_ip = peer[:4]
            peer_ip = socket.inet_ntoa(peer_ip)
            peer_port = int.from_bytes(peer[4:], 'big')
        else:    
            peer = peers[i]
            peer_ip = peer[b'ip'].decode('utf-8')
            peer_port = peer[b'port']
        
        if config.verbose: print(f"Peer ip: {peer_ip} & port: {peer_port}")
        
        try:
            # Create and connect to peer socket
            peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peer_socket.settimeout(0.25)
            peer_socket.connect((peer_ip, peer_port))
            # peer_socket.settimeout(1.0)

            # Send handshake request to peer
            peer_socket.send(handshake_request)
            if config.verbose: print("Send handshake request to peer")
            
            peer_socket.settimeout(0.2)

            new_peer = Peer(peer_socket, peer_ip, peer_port)

            config.connected_peers[peer_socket.fileno()] = new_peer
            config.peer_sockets.append(peer_socket)
            # break

        except ConnectionRefusedError:
            if config.verbose: print("Connected refused... Trying next peer")
            continue    
        except TimeoutError:
            if config.verbose: print("Timeout occured... Trying next peer")
            continue
        except:
            if config.verbose: print("some other error... Trying next peer")
            continue


    config.init_num_peers = len(config.connected_peers)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-s', '--seeding', action='store_true')
    parser.add_argument('-c', '--compact', action='store_true')
    parser.add_argument('-p', '--port', default=0, type=int)
    parser.add_argument('-ja', '--join_address')
    parser.add_argument('-jp', '--join_port', type=int)
    # Start up socket and bind to port
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    config.ip_address = listen_sock.getsockname()[0]
    args = parser.parse_args()
    if args.port == 0:
        config.port = 6881     
        while True:
            try:
                listen_sock.bind(("0.0.0.0", config.port))
                break
            except OSError:
                if config.port < 6889:
                    config.port += 1
                    continue
                else:
                    print("Failed to bind to port reserved for BitTorent now exitting")
                    return
    else:
        config.port = args.port
        listen_sock.bind(("0.0.0.0", config.port))
    listen_sock.listen(10)

    direct_connect = False
    if args.join_address and args.join_port:
        direct_connect = True

    config.compact = args.compact
    config.verbose = args.verbose

    # Open file
    while True:
        try:
            torrent_file = input("Name of torrent file: ")
            with open(torrent_file, "rb") as file:
                buffer = file.read()
            break
        except FileNotFoundError:
            print("File does not exist. Please try again.")
    
    starting_time = time.time()
    # Parse .torrent file
    config.bencode_data = bencodepy.decode(buffer)
    
    # print("Bencode data")
    # print(config.bencode_data)
    
    ## Get needed params
    # Get total num of pieces
    config.total_size = config.bencode_data[b'info'][b'length']
    config.piece_size = config.bencode_data[b'info'][b'piece length']
    config.num_pieces = (config.total_size + config.piece_size - 1) // config.piece_size
    
    if config.verbose: print(f"Total num pieces = {config.num_pieces}")
    
    # Init bitfield for self
    config.self_bitfield = [0] * config.num_pieces
    # Init Piece array
    config.pieces = [Piece(i) for i in range(config.num_pieces)]
    
    # Get announce url and parse to get Tracker host and port
    announce_url = config.bencode_data[b"announce"].decode("utf-8")
    config.parsed_url = urllib.parse.urlparse(announce_url)
    if config.verbose: print(f"(parse) Announce URL: {announce_url}")
    if config.verbose: print(f"(parse) Parse url: {config.parsed_url}")
    
    # Generate info hash
    config.info_hash = hashlib.sha1(bencodepy.encode(config.bencode_data[b"info"])).digest()
    config.url_info_hash = urllib.parse.quote(config.info_hash)
    
    config.peer_id = b"-GT0001-"
    config.peer_id += bytes([random.randint(0, 255) for _ in range(20 - len(config.peer_id))])
    # Set up output file
    config.output_file = config.bencode_data[b'info'][b'name'].decode('utf-8')
    i = 0
    while True:
        if i == 0:
            new_file = config.output_file
        else:
            name, ext = os.path.splitext(config.output_file)
            new_file = f"{name}_{i}{ext}"
        if not os.path.exists(new_file):
            config.output_file = new_file
            break
        i += 1
    with open(config.output_file, "wb") as file:
        pass



    # # config.output_file = config.bencode_data[b'info'][b'name'].decode('utf-8')
    # if direct_connect:
    #     config.output_file = str(config.peer_id) + config.bencode_data[b'info'][b'name'].decode('utf-8')
    # else:
    #     config.output_file = config.bencode_data[b'info'][b'name'].decode('utf-8')

    # try:
    #     with open(config.output_file, "rb") as file:
    #         for idx in range(config.num_pieces):
    #             try:
    #                 file.seek(idx * config.piece_size)
    #                 data = file.read(config.piece_size)
    #                 if hashlib.sha1(data).digest() == config.bencode_data[b'info'][b'pieces'][idx * 20:(idx + 1) * 20]:
    #                     config.self_bitfield[idx] = 1
    #                     config.downloaded += config.piece_size
    #                     config.pieces_complete
    #             except Exception as e: 
    #                 print(e)
    #                 break
    # except FileNotFoundError:
    #      with open(config.output_file, "wb") as file:
    #          pass
            

    if not direct_connect: 
        response = contact_tracker()

        # Seperate http get response header and body depending on server implementation
        carriage_return = True
        body_index = response.find(b'\r\n\r\n')
        if body_index == -1:
            body_index = response.find(b'\n\n')
            carriage_return = False

        # If no seperator found error and just exit
        if body_index == -1:
            print("Error: tracker response does not have body/header seperator")
            return

        # Split the header and body
        header = response[:body_index]
        body_index = body_index + 4 if carriage_return else body_index + 2
        body = response[body_index:]
        body_data = bencodepy.decode(body)

        # Get peers
        peers = body_data[b'peers']

        if config.verbose: print("Num Peers:")
        if config.compact:
            num_peers = len(peers)//6
        else:
            num_peers = len(peers)
        if config.verbose: print("Peer Info:")
        if config.verbose: print(peers)

        # Get interval we can request tracker
        interval = body_data.get(b'interval', 0)

        if config.verbose: print(f"Interval: {interval}")

    ## Test peer protocol
    # Construct handshake request
    pstrlen = 19
    reserved = 0
    if config.verbose: print(config.peer_id)
    handshake_request = pstrlen.to_bytes(1, 'big') + bytes("BitTorrent protocol", 'utf-8') + \
                        reserved.to_bytes(8, 'big') + \
                        config.info_hash + \
                        config.peer_id
    
    config.peer_sockets.append(listen_sock)

    if not direct_connect:
        for i in range(num_peers):  
            if config.compact:
                peer = peers[:6]
                peers = peers[6:]
                
                peer_ip = peer[:4]
                peer_ip = socket.inet_ntoa(peer_ip)
                peer_port = int.from_bytes(peer[4:], 'big')
            else:    
                peer = peers[i]
                peer_ip = peer[b'ip'].decode('utf-8')
                peer_port = peer[b'port']
            
            if config.verbose: print(f"Peer ip: {peer_ip} & port: {peer_port}")
            
            try:
                # Create and connect to peer socket
                peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                peer_socket.settimeout(0.25)
                peer_socket.connect((peer_ip, peer_port))
                # peer_socket.settimeout(1.0)

                # Send handshake request to peer
                peer_socket.send(handshake_request)
                if config.verbose: print("Send handshake request to peer")
                
                peer_socket.settimeout(0.2)

                new_peer = Peer(peer_socket, peer_ip, peer_port)

                config.connected_peers[peer_socket.fileno()] = new_peer
                config.peer_sockets.append(peer_socket)
                # break

            except ConnectionRefusedError:
                if config.verbose: print("Connected refused... Trying next peer")
                continue    
            except TimeoutError:
                if config.verbose: print("Timeout occured... Trying next peer")
                continue
    else:
        peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        peer_socket.settimeout(0.25)
        peer_socket.connect((args.join_address, args.join_port))
        peer_socket.send(handshake_request)
        if config.verbose: print("Send handshake request to peer")
        
        peer_socket.settimeout(0.2)

        new_peer = Peer(peer_socket, args.join_address, args.join_port)

        config.connected_peers[peer_socket.fileno()] = new_peer
        config.peer_sockets.append(peer_socket)

    
    if config.verbose:  print("Connected to peers")
    if config.verbose: print(len(config.connected_peers))
    config.init_num_peers = len(config.connected_peers)
    if config.verbose: print(config.connected_peers)

    last_timeout = time.time()
    config.last_tracker_contact = time.time()

    seeding = False
    prev_pieces_complete = -1

    print()

    while True:
        if config.downloaded == (config.num_pieces * config.piece_size) and not seeding:
            if not config.verbose:
                bar_length = 30
                ticks = '=' * bar_length
                spaces = ' ' * (bar_length - len(ticks))
                print(f'\rDownload: [{ticks}{spaces}] 100% ({int(time.time() - starting_time)} seconds elapsed || {config.num_pieces}/{config.num_pieces})', flush=True)
            if args.seeding:
                print(f"Got the full file, yippee!, entering seeder mode. Took {time.time() - starting_time} seconds")
                add_new_peers()
                seeding = True
            else:
                print(f"Got the full file, yippee! Took {time.time() - starting_time} seconds")
                break
        elif config.downloaded < (config.num_pieces * config.piece_size) and not seeding and not config.verbose:
             curr_percent_downloaded = config.downloaded / (config.num_pieces * config.piece_size) * 100
             if config.pieces_complete > prev_pieces_complete:
                bar_length = 30
                ticks = '=' * int(bar_length * curr_percent_downloaded/100)
                spaces = ' ' * (bar_length - len(ticks))
                print(f'\rDownload: [{ticks}{spaces}] {int(curr_percent_downloaded)}% ({int(time.time() - starting_time)} seconds elapsed || {config.pieces_complete}/{config.num_pieces})', end='',  flush=True)
                prev_pieces_complete = config.pieces_complete
            
        
        timeout = max(0, SELECT_TIMEOUT - (time.time() - last_timeout))
        readable, _, _ = select.select(config.peer_sockets, [], [], timeout)

        if (time.time() - config.last_tracker_contact > 45 and not direct_connect):
            add_new_peers()
            config.last_tracker_contact = time.time()
        if not readable:
            if config.verbose: print("timeout")
            # check if the connected peers are below 20, and if so, contact tracker again
            if len(config.connected_peers) <= config.init_num_peers // 2 or len(config.connected_peers) <= 20 and not direct_connect:
                if config.verbose: print(f"Number of peers dropped to {len(config.connected_peers)}!!!", "*" * 45)
                if time.time() - config.last_tracker_contact < 10:
                    if config.verbose: print("Too soon to contact tracker!")
                else:
                    add_new_peers()
            # check to remove the inactive peers who have not sent a message
            # if we have received a message send a keep alive message
            keep_alives(config.connected_peers)
            last_timeout = time.time()
            
        for sock in readable:
            if sock == listen_sock:
                # means that we have a new peer who wants to connect 
                if config.verbose: print("new peer")
                peer_socket, (ip, port) = sock.accept()
                new_peer = Peer(peer_socket, ip, port)

                config.connected_peers[peer_socket.fileno()] = new_peer
                config.peer_sockets.append(peer_socket)
                r = recv_handshake(new_peer, config.info_hash)
                if r < 0:
                    del config.connected_peers[sock.fileno()]
                    config.peer_sockets.remove(sock)
                    sock.close()
                else:
                    new_peer.handshake_complete = True
                    new_peer.socket.send(handshake_request)
                    new_peer.last_message = time.time()
                r = send_bitfield(new_peer)
                
            else:
                peer = config.connected_peers[sock.fileno()]
                if peer.socket != sock:
                    if config.verbose: print(f"Error w/ peer {peer.ip}:{peer.port}")
                    
                if peer.handshake_complete == False or peer.remove:
                    # recv peer handshake if this fails just remove the peer 
                    # and close the connection
                    r = recv_handshake(peer, config.info_hash)
                    if r < 0 or peer.remove:
                        remove_peer(peer)
                    else:
                        peer.handshake_complete = True
                        peer.last_message = time.time()
                else:
                    # print("(main: while) Recieved message from peer")
                    recv_message(peer)
                    sys.stdout.flush()
                    peer.last_message = time.time()

    # peer_socket.close()

if __name__ == "__main__":
    main()
