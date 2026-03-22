from get_aqi import get_aqi_description


class TestGetAqiDescription:
    def test_good_low(self):
        assert get_aqi_description(0) == "Good"

    def test_good_high(self):
        assert get_aqi_description(50) == "Good"

    def test_moderate_boundary(self):
        assert get_aqi_description(51) == "Moderate"

    def test_moderate_high(self):
        assert get_aqi_description(100) == "Moderate"

    def test_unhealthy_for_sg_boundary(self):
        assert get_aqi_description(101) == "Unhealthy for SG"

    def test_unhealthy_for_sg_high(self):
        assert get_aqi_description(150) == "Unhealthy for SG"

    def test_unhealthy_boundary(self):
        assert get_aqi_description(151) == "Unhealthy"

    def test_unhealthy_high(self):
        assert get_aqi_description(200) == "Unhealthy"

    def test_very_unhealthy_boundary(self):
        assert get_aqi_description(201) == "Very Unhealthy"

    def test_very_unhealthy_high(self):
        assert get_aqi_description(300) == "Very Unhealthy"

    def test_hazardous_boundary(self):
        assert get_aqi_description(301) == "Hazardous"

    def test_hazardous_extreme(self):
        assert get_aqi_description(500) == "Hazardous"
