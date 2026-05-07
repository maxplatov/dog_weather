import requests
from datetime import datetime, timezone

API_URL = "https://api.openweathermap.org/data/2.5/weather"


def get_weather(city: str, api_key: str) -> dict:
    response = requests.get(API_URL, params={
        "q": city,
        "appid": api_key,
        "units": "metric",
        "lang": "ru",
    })
    response.raise_for_status()
    return response.json()


def format_time(unix_ts: int, offset_seconds: int) -> str:
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    local_dt = dt.utctimetuple()
    # Apply timezone offset manually for simple display
    total_seconds = unix_ts + offset_seconds
    local_dt = datetime.utcfromtimestamp(total_seconds)
    return local_dt.strftime("%H:%M")


def print_weather(city: str, api_key: str) -> None:
    data = get_weather(city, api_key)

    name = data["name"]
    temp = data["main"]["temp"]
    feels_like = data["main"]["feels_like"]
    description = data["weather"][0]["description"]
    humidity = data["main"]["humidity"]
    wind_speed = data["wind"]["speed"]
    sunset_ts = data["sys"]["sunset"]
    tz_offset = data["timezone"]

    sunset_time = format_time(sunset_ts, tz_offset)

    print(f"Погода в {name}:")
    print(f"  Температура:  {temp:.1f}°C (ощущается как {feels_like:.1f}°C)")
    print(f"  Описание:     {description.capitalize()}")
    print(f"  Влажность:    {humidity}%")
    print(f"  Ветер:        {wind_speed} м/с")
    print(f"  Закат:        {sunset_time}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Использование: python weather.py <город> <api_key>")
        sys.exit(1)

    print_weather(sys.argv[1], sys.argv[2])
