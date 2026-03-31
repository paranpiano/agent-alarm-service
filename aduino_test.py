import requests

response = requests.post(
    'http://localhost:5000/color',
    json={'r': 255, 'g': 100, 'b': 0}
)

# Show status code
print("Status Code:", response.status_code)

# Show raw response text
print("Response Text:", response.text)

# If the server returns JSON, parse and show it
try:
    print("Response JSON:", response.json())
except ValueError:
    print("No JSON in response")
