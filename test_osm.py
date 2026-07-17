import requests

lat, lon = 13.0, 80.2
radius = 15000
overpass_url = "https://overpass-api.de/api/interpreter"

# Test 1: Using data parameter
query = f"""
[out:json][timeout:25];
node["amenity"="hospital"](around:{radius},{lat},{lon});
out;
"""
print("Querying Overpass...")
try:
    response = requests.post(overpass_url, data=query.encode('utf-8'), headers={'User-Agent': 'BloodRadarBot/1.0'})
    print("Status:", response.status_code)
    data = response.json()
    print("Found:", len(data.get('elements', [])))
except Exception as e:
    print("Error:", e)
    if response:
        print("Raw text:", response.text[:200])

