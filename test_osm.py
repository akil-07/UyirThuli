import requests

def test_osm():
    overpass_url = "https://overpass-api.de/api/interpreter"
    lat, lon = 13.0827, 80.2707 # Chennai
    radius = 15000
    overpass_query = f"""
    [out:json][timeout:25];
    node["amenity"="hospital"](around:{radius},{lat},{lon});
    out;
    """
    headers = {
        'User-Agent': 'BloodRadarBot/1.0'
    }
    response = requests.post(overpass_url, data={'data': overpass_query}, headers=headers)
    print("Status:", response.status_code)
    try:
        data = response.json()
        print("Found:", len(data.get('elements', [])))
        if data.get('elements'):
            print(data['elements'][0])
    except Exception as e:
        print("Error parsing JSON:", e)
        print("Text:", response.text[:500])

if __name__ == '__main__':
    test_osm()
