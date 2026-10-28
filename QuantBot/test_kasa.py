import json
import psutil

try:
    with open('sanal_kasa_kripto.json', 'r') as f:
        print("sanal_kasa_kripto.json:", f.read())
except Exception as e:
    print(e)

print("Check active trades CSV or json...")
