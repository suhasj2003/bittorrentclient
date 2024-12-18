import time
import hashlib

import config

class Peer:
   def __init__(self, socket, ip, port):
      self.socket = socket
      self.ip = ip
      self.port = port
      self.handshake_complete = False
      self.last_message = time.time()
      self.request_pieces = []
      self.pending_pieces = []
      self.choked = True
      self.requested = False
      self.timeout = 0.2
      self.remove = False
      self.max_pieces = 9
      self.num_invalid_messages = 0

   def __str__(self):
      return f"Peer ip: {self.ip} & port: {self.port}"
    
   def __repr__(self):
      return f"Peer({self.ip}, {self.port})"
   
class Piece:
   def __init__(self, idx):
      self.idx = idx # Piece number
      self.peers = [] # Peers who have this piece
      self.requested_peers = [] # Peers who have been requested for this piece
      self.received = False
      self.curr_hash = hashlib.sha1()
      self.amount_recv = 0 # Amount received of this piece
      self.subpieces = [0] * (config.piece_size // config.block_size)
      self.first_request = None
      self.last_request = None
      
   def add_peer(self, peer: Peer):
      self.peers.append(peer)
      
