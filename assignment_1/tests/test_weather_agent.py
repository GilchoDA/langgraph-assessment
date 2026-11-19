import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import sys
import requests

# Add the Weather Agent directory to the Python import path
AGENT_DIR = Path(__file__).resolve().parents[1] / "weather_agent"
sys.path.insert(0, str(AGENT_DIR))

from graph import weather_agent
from components.state import WeatherAgentState
from components.config import config


# Mock location data simulating the IPAPI response
MOCK_LOCATION_DATA = {
    "city": "Mexico City",
    "region": "Mexico City",
    "country_name": "Mexico",
    "latitude": 19.4326,
    "longitude": -99.1332,
    "utc_offset": "-0600",
    "timezone": "America/Mexico_City"
}


# Mock weather data simulating the Open-Meteo response
MOCK_WEATHER_DATA = {
    "latitude": 19.4326,
    "longitude": -99.1332,
    "timezone": "GMT",
    "utc_offset_seconds": 0,
    "current_weather_units": {
        "time": "iso8601",
        "temperature": "°C",
        "windspeed": "km/h",
        "winddirection": "°",
        "weathercode": "wmo code"
    },
    "current_weather": {
        "time": "2026-11-19T18:00",
        "temperature": 24.5,
        "windspeed": 12.4,
        "winddirection": 180,
        "is_day": 1,
        "weathercode": 2
    }
}


class TestWeatherAgent(unittest.TestCase):
    """Integration tests for the Weather Agent."""

    def test_weather_agent_success(self):
        """Test the complete workflow using mocked API responses."""

        # Create the initial agent state
        initial_state = WeatherAgentState(
            name="Test User",
            location_data=None,
            weather_data=None,
            weather_info=None
        )

        # Create the mocked IPAPI response
        mock_location_response = Mock(spec=requests.Response)
        mock_location_response.status_code = 200
        mock_location_response.json.return_value = MOCK_LOCATION_DATA
        mock_location_response.raise_for_status.return_value = None

        # Create the mocked Open-Meteo response
        mock_weather_response = Mock(spec=requests.Response)
        mock_weather_response.status_code = 200
        mock_weather_response.json.return_value = MOCK_WEATHER_DATA
        mock_weather_response.raise_for_status.return_value = None

        # Mock both external HTTP requests
        with patch(
            "components.nodes.requests.get",
            side_effect=[
                mock_location_response,
                mock_weather_response
            ]
        ) as mock_get:

            # Execute the real LangGraph workflow
            final_state = weather_agent.invoke(initial_state)
        # Validate the HTTP requests
        self.assertEqual(mock_get.call_count, 2)

        self.assertEqual(
            mock_get.call_args_list[0].args[0],
            config.LOCATION_API_URL
        )

        self.assertEqual(
            mock_get.call_args_list[0].kwargs,
            {"timeout": config.REQUEST_TIMEOUT}
        )

        self.assertEqual(
            mock_get.call_args_list[1].args[0],
            config.WEATHER_API_BASE_URL
        )

        self.assertEqual(
            mock_get.call_args_list[1].kwargs,
            {
                "params": {
                    "latitude": MOCK_LOCATION_DATA["latitude"],
                    "longitude": MOCK_LOCATION_DATA["longitude"],
                    "current_weather": "true",
                    "timezone": "GMT"
                },
                "timeout": config.REQUEST_TIMEOUT
            }
        )

        # Validate the final agent state
        self.assertEqual(final_state["name"], "Test User")
        self.assertEqual(final_state["location_data"], MOCK_LOCATION_DATA)
        self.assertEqual(final_state["weather_data"], MOCK_WEATHER_DATA)
        self.assertIsNotNone(final_state["weather_info"])

        # Validate the generated weather report
        weather_info = final_state["weather_info"]

        self.assertIn(
            "Time: 18:00 UTC | 12:00 (UTC-0600)",
            weather_info
        )
        self.assertIn("Good morning, Test User!", weather_info)
        self.assertIn(
            "Your current location: Mexico City, Mexico City, Mexico",
            weather_info
        )
        self.assertIn("Partly cloudy", weather_info)
        self.assertIn("Temperature: 24.5°C (comfortable)", weather_info)
        self.assertIn("Wind: 12.4 km/h", weather_info)

        # Validate the complete formatted report
        expected_weather_info = (
            "Time: 18:00 UTC | 12:00 (UTC-0600)\n\n"
            "Good morning, Test User!\n\n"
            "Your current location: Mexico City, Mexico City, Mexico\n\n"
            "Current weather conditions:\n"
            "• Partly cloudy\n"
            "• Temperature: 24.5°C (comfortable)\n"
            "• Wind: 12.4 km/h"
        )

        self.assertEqual(weather_info, expected_weather_info)

    def test_location_api_rate_limit(self):
        """Test the workflow when IPAPI returns HTTP 429."""

        # Create the initial agent state
        initial_state = WeatherAgentState(
            name="Test User",
            location_data=None,
            weather_data=None,
            weather_info=None
        )

        # Create a mocked HTTP 429 response
        mock_location_response = Mock(spec=requests.Response)
        mock_location_response.status_code = 429

        mock_location_response.raise_for_status.side_effect = (
            requests.exceptions.HTTPError(
                "429 Client Error: Too Many Requests for url: "
                "https://ipapi.co/json/"
            )
        )

        # Mock the external HTTP request
        with patch(
            "components.nodes.requests.get",
            return_value=mock_location_response
        ) as mock_get:

            # Validate that the workflow raises the expected exception
            with self.assertRaises(Exception) as context:
                weather_agent.invoke(initial_state)

        # Validate the error message
        self.assertIn(
            "Failed to fetch location data",
            str(context.exception)
        )

        self.assertIn("429", str(context.exception))
        self.assertIn("Too Many Requests", str(context.exception))

        # Validate that only the location API was called
        mock_get.assert_called_once_with(
            config.LOCATION_API_URL,
            timeout=config.REQUEST_TIMEOUT
        )

        # Validate that the failed response was not processed
        mock_location_response.raise_for_status.assert_called_once()
        mock_location_response.json.assert_not_called()

    def test_weather_agent_custom_wind_unit(self):
        """Test dynamic wind unit formatting."""

        # Create the initial agent state
        initial_state = WeatherAgentState(
            name="Test User",
            location_data=None,
            weather_data=None,
            weather_info=None
        )

        # Create weather data with a different wind unit
        custom_weather_data = {
            **MOCK_WEATHER_DATA,
            "current_weather_units": {
                **MOCK_WEATHER_DATA["current_weather_units"],
                "windspeed": "mph"
            }
        }

        # Create mocked API responses
        mock_location_response = Mock(spec=requests.Response)
        mock_location_response.json.return_value = MOCK_LOCATION_DATA
        mock_location_response.raise_for_status.return_value = None

        mock_weather_response = Mock(spec=requests.Response)
        mock_weather_response.json.return_value = custom_weather_data
        mock_weather_response.raise_for_status.return_value = None

        # Execute the workflow using mocked responses
        with patch(
            "components.nodes.requests.get",
            side_effect=[
                mock_location_response,
                mock_weather_response
            ]
        ):
            final_state = weather_agent.invoke(initial_state)

        # Validate dynamic wind unit formatting
        weather_info = final_state["weather_info"]

        self.assertIn("Wind: 12.4 mph", weather_info)
        self.assertNotIn("Wind: 12.4 km/h", weather_info)