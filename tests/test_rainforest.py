import base64
import logging

from rainforest_loop import (
    format_load_string,
    create_request_body,
    create_request_headers,
    extract_load_from_xml,
)


class MockConfig:
    """Minimal stand-in for configparser.ConfigParser."""
    def __init__(self, data):
        self._data = data

    def get(self, section, key):
        return self._data[key]


# --- format_load_string ---

class TestFormatLoadString:
    def test_plain_number(self):
        assert format_load_string("2.151") == "2.151"

    def test_strips_whitespace(self):
        assert format_load_string("  2.151  ") == "2.151"

    def test_integer_input(self):
        assert format_load_string("3") == "3.000"

    def test_zero(self):
        assert format_load_string("0") == "0.000"

    def test_invalid_string_returns_none(self):
        assert format_load_string("not_a_number") is None

    def test_none_input_returns_none(self):
        assert format_load_string(None) is None


# --- extract_load_from_xml ---

VALID_XML = b"""<Device>
  <Components>
    <Component>
      <Name>Main</Name>
      <Variables>
        <Variable>
          <Name>zigbee:InstantaneousDemand</Name>
          <Value>2.151</Value>
          <Units>kW</Units>
        </Variable>
      </Variables>
    </Component>
  </Components>
</Device>"""

WRONG_VARIABLE_XML = b"""<Device>
  <Components>
    <Component>
      <Name>Main</Name>
      <Variables>
        <Variable>
          <Name>zigbee:SomethingElse</Name>
          <Value>2.151</Value>
          <Units>kW</Units>
        </Variable>
      </Variables>
    </Component>
  </Components>
</Device>"""


class TestExtractLoadFromXml:
    def test_valid_xml_returns_load(self):
        result = extract_load_from_xml(VALID_XML)
        assert result == "2.151"

    def test_wrong_variable_name_returns_none(self):
        assert extract_load_from_xml(WRONG_VARIABLE_XML) is None

    def test_invalid_xml_returns_none(self):
        assert extract_load_from_xml(b"this is not xml") is None

    def test_empty_bytes_returns_none(self):
        assert extract_load_from_xml(b"") is None


# --- create_request_body ---

class TestCreateRequestBody:
    def test_contains_hardware_address(self):
        config = MockConfig({'hardware_address': '0xABCD1234'})
        body = create_request_body(config, logging)
        assert '<HardwareAddress>0xABCD1234</HardwareAddress>' in body

    def test_contains_demand_variable(self):
        config = MockConfig({'hardware_address': '0xABCD1234'})
        body = create_request_body(config, logging)
        assert 'zigbee:InstantaneousDemand' in body

    def test_contains_device_query_command(self):
        config = MockConfig({'hardware_address': '0xABCD1234'})
        body = create_request_body(config, logging)
        assert '<Name>device_query</Name>' in body


# --- create_request_headers ---

class TestCreateRequestHeaders:
    def test_authorization_header_correct(self):
        config = MockConfig({'username': 'testuser', 'password': 'testpass'})
        headers = create_request_headers(config, logging)
        expected_b64 = base64.b64encode(b'testuser:testpass').decode('UTF-8')
        assert headers['Authorization'] == f'Basic {expected_b64}'

    def test_content_type_header(self):
        config = MockConfig({'username': 'testuser', 'password': 'testpass'})
        headers = create_request_headers(config, logging)
        assert headers['Content-type'] == 'application/x-www-form-urlencoded'

    def test_special_chars_in_credentials(self):
        config = MockConfig({'username': 'user@host', 'password': 'p@ss:w0rd'})
        headers = create_request_headers(config, logging)
        expected_b64 = base64.b64encode(b'user@host:p@ss:w0rd').decode('UTF-8')
        assert headers['Authorization'] == f'Basic {expected_b64}'
