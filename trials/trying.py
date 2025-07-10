import urllib
import urllib.parse

query = "OLED TV 8K, HDR, Dolby Atmos"
print(urllib.parse.quote(query))
print(urllib.parse.quote(query, safe=''))