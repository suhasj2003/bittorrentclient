import socket
import time
import hashlib

import config

def recv_handshake(peer, info_hash):
   try:
      pstrlen = peer.socket.recv(1)
      pstrlen = int.from_bytes(pstrlen, "big")
      pstr = peer.socket.recv(pstrlen)
      reserved = peer.socket.recv(8)
      peer_info_hash = peer.socket.recv(20)
      peer_id = peer.socket.recv(20)
      if info_hash != peer_info_hash:
         return -1 
        
      if pstr.decode('utf-8') != "BitTorrent protocol":
         return -2
        
      if config.verbose: print("Received handshake response from peer")
      return 0
   except (ConnectionResetError, TimeoutError):
      if config.verbose: print("Connection reset by peer")
      return -4
    
def recv_message(peer):
   # Message length
   length = safe_recv(peer, 4)
   if not length:
      peer.remove = True
      return
   length = int.from_bytes(length, "big")

   if length == 0:
      # Keep alive, do nothing
      return
   
   id = safe_recv(peer, 1)
   if not id:
      return
   id = int.from_bytes(id, "big")

   if id == 0:
      if config.verbose: print(f"(recv_handshake: choke) Choke message from {peer.ip}:{peer.port}")
      # Reset Peer's Pieces
      for piece_idx in peer.pending_pieces:
         piece = config.pieces[piece_idx]
         piece.requested_peers.remove(peer)
         
      # Reset Peer
      peer.pending_pieces.clear()
      peer.requested = False
           
      peer.choked = True
   elif id == 1:
      if config.verbose: print(f"(recv_handshake) Unchoke message from {peer.ip}:{peer.port}")
      peer.choked = False
      
      request_new_piece(peer)
         
   elif id == 2:
      if config.verbose: print(f"(recv_handshake) Interested message from {peer.ip}:{peer.port}")
      # Unchoke the peer
      unchoke_msg = b'\x00\x00\x00\x01\x01'
      try:
         peer.socket.send(unchoke_msg)
      except BrokenPipeError:
         print("failed to send unchoke")
         return
      if config.verbose: print(f"Sent 'unchoke' message to {peer.ip}:{peer.port}")
   elif id == 3:
      if config.verbose: print("(recv_handshake) not-interested message")
      # No payload
      return
   elif id == 4:
      if config.verbose: print("(recv_handshake) have message")
      piece_index = peer.socket.recv(4)
      piece_index = int.from_bytes(piece_index, "big")
      if config.verbose: print(f"(have) Peer {peer.ip}:{peer.port} has piece {piece_index}")
      if (piece_index < 0 or piece_index > config.num_pieces):
         if config.verbose: print("(have) Invalid piece index")
         return
      if config.self_bitfield[piece_index] == 0:
         peer.request_pieces.append(piece_index) 
         ## TODO: maybe if nothing is being requested from them request this
      # update bitfield of peer
      request_new_piece(peer)

   elif id == 5:
      if config.verbose: print("(recv_handshake) bitfield message")
      bitfield = peer.socket.recv(length - 1)
      converted_bitfield = [0] * config.num_pieces
      for i in range(len(bitfield)):
         byte = bitfield[i]
         for j in range(8): # Iterate through each bit
            idx = i * 8 + j
            if idx >= config.num_pieces:
               break
            if byte & (1 << (7 - j)): # If non-zero, set to 1
               converted_bitfield[idx] = 1
               config.pieces[idx].add_peer(peer)

      # Generate pieces to request from peer
      peer.request_pieces = [i for i in range(len(converted_bitfield)) if converted_bitfield[i] == 1 and config.self_bitfield[i] == 0]
      
      # If peer has pieces we want, send interested msg
      if (len(peer.request_pieces) > 0):
         interested_msg = b'\x00\x00\x00\x01\x02'
         try:
            peer.socket.send(interested_msg)
         except BrokenPipeError:
            return
         if config.verbose: print("(recv_handshake: bitfield) Sent interested msg to peer")
      else:
         not_interested_msg = b'\x00\x00\x00\x01\x03'
         try:
            peer.socket.send(not_interested_msg)
         except BrokenPipeError:
            return
         if config.verbose: print("(recv_handshake: bitfield) Sent not interested msg to peer")

   elif id == 6:
      if config.verbose: print(f"(recv_handshake) request message from {peer.ip}:{peer.port}")
      piece_idx = peer.socket.recv(4)
      piece_idx = int.from_bytes(piece_idx, "big")
      begin = peer.socket.recv(4)
      begin = int.from_bytes(begin, "big")
      length = peer.socket.recv(4)
      length = int.from_bytes(length, "big")
      if config.verbose: print("trying to send piece message")
      if piece_idx <= len(config.pieces) or (begin + length) <= config.piece_size:
         piece_msg = int.to_bytes(length + 9, 4, 'big')
         piece_msg += int.to_bytes(7, 1, 'big')
         piece_msg += int.to_bytes(piece_idx, 4, 'big')
         piece_msg += int.to_bytes(begin, 4, 'big')
         with open(config.output_file, "rb") as file:
               file.seek(piece_idx * config.piece_size + begin)
               data = file.read(length)
               piece_msg += data
         try:
            if config.verbose: print("trying to send piece message")
            peer.socket.send(piece_msg)
            config.uploaded += length
            if config.verbose: print(f"Sent piece message for piece index: {piece_idx}, begin: {begin}, length {length}")
         except BrokenPipeError:
            return

   elif id == 7:
      if config.verbose: print(f"(recv_handshake) Received piece message from {peer.ip}:{peer.port}")
      
      # Receive piece data
      piece_idx = peer.socket.recv(4)
      piece_idx = int.from_bytes(piece_idx, "big")
      begin = peer.socket.recv(4)
      begin = int.from_bytes(begin, "big")
      piece_data = safe_recv(peer, length - 9)
      if not piece_data:
         return
      amount_recv = len(piece_data)
      while amount_recv != (length - 9):
         subpiece_data = safe_recv(peer, (length - 9) - amount_recv)
         if not subpiece_data:
            return
         amount_recv += len(subpiece_data)
         piece_data += subpiece_data
         
      # If peer is responding after choked, deffo bad data    
      if peer.choked:
         return
      
      if piece_idx not in peer.request_pieces:
         return
      
      if config.verbose: print(f"Received piece idx = {piece_idx}, begin = {begin}, piece data len = {len(piece_data)}")
      
      piece = config.pieces[piece_idx]
      
      # If peer is sending us late data, ignore
      # if peer not in piece.requested_peers:
      #    return
      
      # If peer is sending us data we do not need, ignore
      if (begin != piece.amount_recv):
         return
      
      peer.requested = False
      
      # Update the Piece information
      piece.subpieces[begin // config.block_size] = piece_data
      piece.amount_recv += config.block_size
      piece.curr_hash.update(piece_data)

      # with open(config.output_file, "r+b") as file:
      #    file.seek(piece_idx * config.piece_size + begin)

      if piece.amount_recv == config.piece_size:
         # Check hash the received piece
         if config.verbose: print("(piece) Received full piece")
         expected_hash = config.bencode_data[b'info'][b'pieces'][piece_idx * 20:(piece_idx + 1) * 20]
         if expected_hash == piece.curr_hash.digest():
            # Update Piece
            piece = config.pieces[piece_idx]
            piece.received = True
            if config.verbose: print("(piece) Hash matched")
            if config.verbose: print(f"(piece) Got {piece_idx}, first request was {time.time() - piece.first_request} seconds ago, last request was {time.time() - piece.last_request} seconds ago")
            if peer in piece.requested_peers:
               piece.requested_peers.remove(peer)
            if piece_idx in peer.request_pieces:
               peer.request_pieces.remove(piece_idx)
            peer.pending_pieces.remove(piece_idx)
            
            # Store piece into external file            
            if config.verbose: print(f"(piece) Num subpieces = {len(piece.subpieces)} & Expected subpieces = {((config.piece_size // config.block_size))}")
         
            with open(config.output_file, "r+b") as file:
               file.seek(piece_idx * config.piece_size)
               for subpiece in piece.subpieces:
                  file.write(subpiece)
            piece.subpieces = []
               
            config.downloaded += config.piece_size 
            config.self_bitfield[piece_idx] = 1
            config.pieces_complete += 1
            
            have_message = b'\x00\x00\x00\x05\x04'
            have_message += piece_idx.to_bytes(4, 'big')

            for sock in config.peer_sockets:
               try:
                  sock.send(have_message)
               except BrokenPipeError:
                  continue
               except ConnectionResetError:
                  continue
               except TimeoutError:
                  continue
            if config.verbose: print(f"(piece) Sent 'have' message for piece {piece_idx}")

            # Request new piece from the peer
            request_new_piece(peer)
            
            return
         else:
            if config.verbose: print(f"(piece) Hash did not match")
            piece.amount_recv = 0
            piece.curr_hash = hashlib.sha1()
            piece.requested_peers.remove(peer)
            peer.pending_pieces.remove(piece_idx)
            
            request_new_piece(peer)
      
      for requested_peer in piece.requested_peers:
         if not requested_peer.choked:
            request_msg = construct_request(piece_idx, piece.amount_recv)
            safe_send(requested_peer, request_msg)
      
   elif id == 8:
      if config.verbose: print("(recv_handshake) cancel mesage")
      # piece_idx = peer.socket.recv(4)
      # piece_idx = int.from_bytes(piece_idx, "big")
      # begin = peer.socket.recv(4)
      # begin = int.from_bytes(begin, "big")
      # length = peer.socket.recv(4)
      # length = int.from_bytes(length, "big")
   elif id == 9:
      if config.verbose: print("(recv_handshake) port message")
      port = peer.socket.recv(4)
   else:
      if config.verbose: print(f"(recv_handshake) invalid message id from {peer.ip}:{peer.port}")
      peer.num_invalid_messages += 1
      if (peer.num_invalid_messages >= 10):
         remove_peer(peer)
      return

def construct_request(piece_idx, begin):
   request_msg = b'\x00\x00\x00\x0d\x06' # ID
   request_msg += piece_idx.to_bytes(4, 'big')
   request_msg += begin.to_bytes(4, 'big')
   
   # Calculate length
   remaining = config.piece_size - begin
   length = min(remaining, config.block_size)
   
   request_msg += length.to_bytes(4, 'big')

   return request_msg

def request_new_piece(peer):
   # If nothing to request or request pending, return
   if len(peer.request_pieces) == 0:
      if config.verbose: print("No more to request or already requested")
      return
      
   ## We can fix this later if necessary
   # if len(peer.pending_pieces) > 0:
   #    piece_idx = peer.pending_pieces[0]
   #    piece = config.pieces[piece_idx]
   #    request_msg = construct_request(piece_idx, piece.amount_recv)
   #    peer.socket.send(request_msg)
   #    print(f"(unchoke) Sent 'request' message for piece {piece_idx} begin {piece.amount_recv} to peer {peer.ip}:{peer.port}")
   #    peer.requested = True
      
   # Iterate through potential pieces to request from peer
   for piece_idx in peer.request_pieces:
      # Get piece data
      piece = config.pieces[piece_idx]
      
      if len(peer.pending_pieces) >= peer.max_pieces:
         return
         
      # If piece already received or piece already requested or peer has request pending, continue
      if piece.received or ((config.downloaded / (config.num_pieces * config.piece_size) < 0.99) and len(piece.requested_peers) > 0):
         continue
         
      # Construct request msg
      request_msg = construct_request(piece_idx, piece.amount_recv)
      safe_send(peer, request_msg)
      
      # try:
      #    peer.socket.send(request_msg)
      # except BrokenPipeError:
      #    return
      if config.verbose: print(f"(piece) Sent 'request' message for piece {piece_idx} begin {piece.amount_recv} to peer {peer.ip}:{peer.port}")
      peer.requested = True
         
      # Add peer to piece requested peers
      piece.requested_peers.append(peer)
      peer.pending_pieces.append(piece_idx)
      if piece.first_request == None:
         piece.first_request = time.time()
      piece.last_request = time.time()
         
      peer.requested = True
      
def safe_recv(peer, length):
   try:
      data = peer.socket.recv(length)
      return data
   except (TimeoutError, ValueError):
      # Reset Peer's Pieces
      for piece_idx in peer.pending_pieces:
         piece = config.pieces[piece_idx]
         piece.requested_peers.remove(peer)
         
      # Reset Peer
      peer.pending_pieces.clear()
      peer.requested = False
      
      # Set to choked and send Interested msg to check
      # if peer can still continue relationship
      peer.choked = True
      
      peer.timeout += 0.01
      
      # if (peer.timeout > 0.5):
      #    peer.remove = True
      #    # print(f"Removing peer {peer.port}:{peer.ip}, too many timeouts!")
      #    return
      peer.socket.settimeout(peer.timeout)
      
      interested_msg = b'\x00\x00\x00\x01\x02'
      try:
         peer.socket.send(interested_msg)
      except BrokenPipeError:
         peer.remove = True
         return None
      if config.verbose: print(f"(safe_recv) Sent 'interested' message to peer {peer.ip}:{peer.port}")
      return None

def safe_send(peer, message):
   try:
      peer.socket.send(message)
      return 1
   except BrokenPipeError: # Peer not long usable
      # Reset Peer's Pieces
      if config.verbose: print(f"(piece) Peer {peer.ip}:{peer.port} closed connection")
      for piece_idx in peer.pending_pieces:
         piece = config.pieces[piece_idx]
         piece.requested_peers.remove(peer)
            
      # Reset Peer
      peer.pending_pieces.clear()
      peer.requested = False
         
      # Set to choked
      peer.choked = True
      peer.remove = True
      return -1
   except:
      if config.verbose: print("Something terrible has happened... removing peer")
      remove_peer(peer)
      return -1
   
def keep_alives(connected_peers):
   currtime = time.time()
   peers_to_remove = []
   for peer in connected_peers.values():
      if currtime - peer.last_message > 120:
         peers_to_remove.append(peer)
      else:
         keep_alive = b'\x00\x00\x00\x00'
         try:
            safe_send(peer, keep_alive)
         except BrokenPipeError:
            continue
         except TimeoutError:
            continue
   
   if config.verbose: print(f"Removing {len(peers_to_remove)} peers")
   for peer in peers_to_remove:
      remove_peer(peer)

def send_bitfield(peer):
   num_bits = len(config.self_bitfield)
   num_bytes = (num_bits + 7) // 8  # Calculate the number of bytes required
   length = 1 + num_bytes
   bitfield_msg = int.to_bytes(length, 4, 'big')
   bitfield_msg += int.to_bytes(5, 1, 'big')
   
   packed_bytes = bytearray()
   for i in range(num_bytes):
      byte_value = 0
      for j in range(8):
         index = i * 8 + j
         if index < num_bits:
               byte_value |= config.self_bitfield[index] << (7 - j)
      packed_bytes.append(byte_value)

   bitfield_msg += packed_bytes
   peer.socket.send(bitfield_msg)

def remove_peer(peer):
   if peer.socket.fileno() not in config.connected_peers:
      if config.verbose: print("Definitely some logic error with handling of removing peers, sort it out later")
      return

   del config.connected_peers[peer.socket.fileno()]
   if config.verbose: print(f"Removing peer {peer.ip}:{peer.port}")
   config.peer_sockets.remove(peer.socket)
   for piece in peer.request_pieces:
      temp_piece = config.pieces[piece]
      if peer in temp_piece.peers:
         temp_piece.peers.remove(peer)
      if peer in temp_piece.requested_peers:
         temp_piece.requested_peers.remove(peer)
   peer.socket.close()
