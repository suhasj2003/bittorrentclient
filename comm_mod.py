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
        
      print("Received handshake response from peer")
      return 0
   except (ConnectionResetError, TimeoutError):
      print("Connection reset by peer")
      return -4
    
def recv_message(peer):
   # message length
   # length = peer.socket.recv(4)
   length = safe_recv(peer, 4)
   if not length:
      return
   length = int.from_bytes(length, "big")

   if length == 0:
      # print("(recv_handshake) keep alive")
      return
    
   # id = peer.socket.recv(1)
   id = safe_recv(peer, 1)
   if not id:
      return
   id = int.from_bytes(id, "big")

   if id == 0:
      print(f"(recv_handshake: choke) Choke message from {peer.ip}:{peer.port}")
      # Reset Peer's Pieces
      for piece_idx in peer.pending_pieces:
         piece = config.pieces[piece_idx]
         piece.requested_peers.remove(peer)
         piece.amount_recv = 0
         piece.curr_hash = hashlib.sha1()
         
      # Reset Peer
      peer.pending_pieces.clear()
      peer.requested = False
      
      # peer.max_pieces -= 1
      # if (peer.max_pieces == 0):
      #    peer.remove = True      
      peer.choked = True
      # if (peer.requested):
      #    interested_msg = b'\x00\x00\x00\x01\x02'
      #    peer.socket.send(interested_msg)
      #    print("(recv_handshake: choke) Sent interested msg to peer")
   elif id == 1:
      print(f"(recv_handshake) Unchoke message from {peer.ip}:{peer.port}")
      peer.choked = False
      
      request_new_piece(peer)
         
   elif id == 2:
      print(f"(recv_handshake) Interested message from {peer.ip}:{peer.port}")
      # Unchoke the peer
      unchoke_msg = b'\x00\x00\x00\x01\x01'
      try:
         peer.socket.send(unchoke_msg)
      except BrokenPipeError:
         return
      print(f"Sent 'unchoke' message to {peer.ip}:{peer.port}")
   elif id == 3:
      print("(recv_handshake) not-interested message")
   elif id == 4:
      print("(recv_handshake) have message")
      piece_index = peer.socket.recv(4)
      piece_index = int.from_bytes(piece_index, "big")
      print(f"(have) Peer {peer.ip}:{peer.port} has piece {piece_index}")
      if (piece_index < 0 or piece_index > config.num_pieces):
         print("(have) Invalid piece index")
         return
      if config.self_bitfield[piece_index] == 0:
         peer.request_pieces.append(piece_index) 
         ## TODO: maybe if nothing is being requested from them request this
      # update bitfield of peer
   elif id == 5:
      print("(recv_handshake) bitfield message")
      bitfield = peer.socket.recv(length - 1)
      # print(f"Bitfieldlen = {len}, Bitfieldid = {id}, Bitfield = {bitfield}")
        
      converted_bitfield = [0] * config.num_pieces
        
      for i in range(len(bitfield)):
         byte = bitfield[i]
         for j in range(8): # Iterate through each bit
            idx = i * 8 + j
            if idx >= config.num_pieces:
               break
            if byte & (1 << (7 - j)): # If non-zero, set to 1
               converted_bitfield[idx] = 1
               config.pieces[idx].add_peer(peer) # Might be better to just store socket ?
               # print(f"Piece #{idx}")
               # print(config.pieces[idx].peers)

      # Generate pieces to request from peer
      peer.request_pieces = [i for i in range(len(converted_bitfield)) if converted_bitfield[i] == 1 and config.self_bitfield[i] == 0]
      
      # If peer has pieces we want, send interested msg
      if (len(peer.request_pieces) > 0):
         interested_msg = b'\x00\x00\x00\x01\x02'
         try:
            peer.socket.send(interested_msg)
         except BrokenPipeError:
            return
         print("(recv_handshake: bitfield) Sent interested msg to peer")
      else:
         not_interested_msg = b'\x00\x00\x00\x01\x03'
         try:
            peer.socket.send(not_interested_msg)
         except BrokenPipeError:
            return
         print("(recv_handshake: bitfield) Sent not interested msg to peer")
        
      # print(f"Converted bitfield = {converted_bitfield}")
      # print(f"Pieces to request = {request_pieces}")

   elif id == 6:
      print("(recv_handshake) request message")
      piece_idx = peer.socket.recv(4)
      piece_idx = int.from_bytes(piece_idx, "big")
      begin = peer.socket.recv(4)
      begin = int.from_bytes(begin, "big")
      length = peer.socket.recv(4)
      length = int.from_bytes(length, "big")
      if piece_idx < len(config.pieces) & (begin + length) <= config.piece_size:
         piece_msg = int.to_bytes(length + 9, 4, 'big')
         piece_msg += int.to_bytes(7, 1, 'big')
         piece_msg += int.to_bytes(begin, 4, 'big')
         with open(config.output_file, "r+b") as file:
               file.seek(piece_idx * config.piece_size)
               piece_msg += file.read(length)
         peer.socket.send(piece_msg)

   elif id == 7:
      print(f"(recv_handshake) Received piece message from {peer.ip}:{peer.port}")
      
      # Receive piece data
      piece_idx = peer.socket.recv(4)
      piece_idx = int.from_bytes(piece_idx, "big")
      begin = peer.socket.recv(4)
      begin = int.from_bytes(begin, "big")

      # piece_data = peer.socket.recv(length - 9)
      piece_data = safe_recv(peer, length - 9)
      if not piece_data:
         return
      amount_recv = len(piece_data)
      while amount_recv != (length - 9):
         # subpiece_data = peer.socket.recv((length - 9) - amount_recv)
         subpiece_data = safe_recv(peer, (length - 9) - amount_recv)
         if not subpiece_data:
            return
         amount_recv += len(subpiece_data)
         piece_data += subpiece_data
         
      # If peer is responding after choked, deffo bad data    
      if peer.choked or piece_idx not in peer.request_pieces:
         return
      
      print(f"Received piece idx = {piece_idx}, begin = {begin}, piece data len = {len(piece_data)}")
      
      piece = config.pieces[piece_idx]
      
      # If peer is sending us late data, ignore
      if peer not in piece.requested_peers:
         return
      
      # If peer is sending us data we do not need, ignore
      if (begin != piece.amount_recv):
         return
      
      peer.requested = False
      
      # Update the Piece information
      piece.subpieces[begin // config.block_size] = piece_data
      piece.amount_recv += config.block_size
      piece.curr_hash.update(piece_data)

      if piece.amount_recv == config.piece_size:
         # Check hash the received piece
         print("(piece) Received full piece")
         expected_hash = config.bencode_data[b'info'][b'pieces'][piece_idx * 20:(piece_idx + 1) * 20]
         if expected_hash == piece.curr_hash.digest():
            print("(piece) Hash matched")
            print(f"(piece) Got {piece_idx}")
            # Update Piece
            piece = config.pieces[piece_idx]
            piece.received = True
            piece.requested_peers.remove(peer)
            if piece_idx in peer.request_pieces:
               peer.request_pieces.remove(piece_idx)
            peer.pending_pieces.remove((piece_idx, _))
            
            # Store piece into external file            
            print(f"(piece) Num subpieces = {len(piece.subpieces)} & Expected subpieces = {((config.piece_size // config.block_size) + 1)}")
         
            with open(config.output_file, "r+b") as file:
               file.seek(piece_idx * config.piece_size)
               for subpiece in piece.subpieces:
                  file.write(subpiece)
            piece.subpieces = []
               
            config.downloaded += config.piece_size 
            
            have_message = b'\x00\x00\x00\x05\x04'
            have_message += piece_idx.to_bytes(4, 'big')

            for sock in config.peer_sockets:
               try:
                  sock.send(have_message)
               except BrokenPipeError:
                  continue
               except ConnectionResetError:
                  continue
            print(f"(piece) Sent 'have' message for piece {piece_idx}")

            # Request new piece from the peer
            request_new_piece(peer)
            
            return
         else:
            print(f"(piece) Hash did not match")
            piece.amount_recv = 0
            piece.curr_hash = hashlib.sha1()
      
      if not peer.choked:
         request_msg = construct_request(piece_idx, piece.amount_recv)
         safe_send(peer, request_msg)
         # try:
         #    peer.socket.send(request_msg)
         # except BrokenPipeError:
         #    return
      else:
         print("(piece) Peer choked cannot send msg, wait for unchoke")
         interested_msg = b'\x00\x00\x00\x01\x02'
         try:
            peer.socket.send(interested_msg)
         except BrokenPipeError:
            return
         print("(piece) Sent interested msg to peer")
      
   elif id == 8:
      print("(recv_handshake) cancel mesage")
      piece_idx = peer.socket.recv(4)
      piece_idx = int.from_bytes(piece_idx, "big")
      begin = peer.socket.recv(4)
      begin = int.from_bytes(begin, "big")
      length = peer.socket.recv(4)
      length = int.from_bytes(length, "big")
   elif id == 9:
      print("(recv_handshake) port message")
      port = peer.socket.recv(4)
   else:
      return
      # print("(recv_handshake) invalid message id")

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
      print("No more to request or already requested")
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
      
      if len(peer.pending_pieces) > peer.max_pieces:
         return
         
      # If piece already received or piece already requested or peer has request pending, continue
      if piece.received or ((config.downloaded / (config.num_pieces * config.piece_size) < 0.99) and len(piece.requested_peers) > 0):
         continue
         
      # Construct request msg
      request_msg = construct_request(piece_idx, 0)
      safe_send(peer, request_msg)
      
      # try:
      #    peer.socket.send(request_msg)
      # except BrokenPipeError:
      #    return
      print(f"(piece) Sent 'request' message for piece {piece_idx} begin {piece.amount_recv} to peer {peer.ip}:{peer.port}")
      peer.requested = True
         
      # Add peer to piece requested peers
      piece.requested_peers.append(peer)
      peer.pending_pieces.append((piece_idx, time.time()))
         
      peer.requested = True
      
def safe_recv(peer, length):
   try:
      data = peer.socket.recv(length)
      return data
   except (TimeoutError, ValueError):
      # Reset Peer's Pieces
      for piece_idx, _ in peer.pending_pieces:
         piece = config.pieces[piece_idx]
         piece.requested_peers.remove(peer)
         piece.amount_recv = 0
         piece.curr_hash = hashlib.sha1()
         
      # Reset Peer
      peer.pending_pieces.clear()
      peer.requested = False
      
      # Set to choked and send Interested msg to check
      # if peer can still continue relationship
      peer.choked = True
      
      peer.timeout += 0.05
      
      # if (peer.timeout > 0.5):
      #    peer.remove = True
      #    # print(f"Removing peer {peer.port}:{peer.ip}, too many timeouts!")
      #    return
      peer.socket.settimeout(peer.timeout)
      
      interested_msg = b'\x00\x00\x00\x01\x02'
      try:
         peer.socket.send(interested_msg)
      except BrokenPipeError:
         return
      print(f"(safe_recv) Sent 'interested' message to peer {peer.ip}:{peer.port}")

def safe_send(peer, message):
   try:
      peer.socket.send(message)
      return 1
   except BrokenPipeError: # Peer not long usable
      # Reset Peer's Pieces
      print(f"(piece) Peer {peer.ip}:{peer.port} closed connection")
      for piece_idx, _ in peer.pending_pieces:
         piece = config.pieces[piece_idx]
         piece.requested_peers.remove(peer)
         piece.amount_recv = 0
         piece.curr_hash = hashlib.sha1()
            
      # Reset Peer
      peer.pending_pieces.clear()
      peer.requested = False
         
      # Set to choked
      peer.choked = True
      return -1
   
def keep_alives(connected_peers):
   currtime = time.time()
   for peer in connected_peers:
      if currtime - peer.last_message > 120:
         connected_peers.remove(peer)
         peer.socket.close()
      else:
         keep_alive = b'\x00\x00\x00\x00'
         try:
            peer.socket.send(peer, keep_alive)
         except BrokenPipeError:
            continue
