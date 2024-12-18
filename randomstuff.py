import random

sampleList = [100, 200, 300, 400, 500]
n = len(sampleList)
weights = tuple([(3*(n - i)) for i in range(n)])
randomList = random.choices(
  sampleList, weights=weights, k=5)
 
print(randomList)