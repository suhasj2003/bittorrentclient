with open("output.txt", "r") as file:
   lines = file.readlines()

pieces = []
for line in lines:
   if "(piece) Got" in line:
      piece_number = int(line.split()[2])
      pieces.append(piece_number)

missing_pieces = []
for i in range(2512):
   if i not in pieces:
      missing_pieces.append(i)

if missing_pieces:
   print(f"Missing {len(missing_pieces)} pieces:")
   print(", ".join(str(piece) for piece in missing_pieces))