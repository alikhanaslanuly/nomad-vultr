#!/usr/bin/env bash
echo "[*] Pre-warming 1000MB in-memory cache..."
python3 -c "
chunks = []
print('Allocating blocks...')
for i in range(20):
    chunks.append(bytearray(50 * 1024 * 1024))
    print(f'Allocated {(i+1)*50} MB')
print('Allocation done!')
"
