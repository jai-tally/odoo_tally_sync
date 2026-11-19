# -*- coding: utf-8 -*-
"""
TallyPrime HTTP Client
Handles sending XML payloads to TallyPrime and validating import status.
"""
import requests
import logging
from xml.etree import ElementTree as ET

_logger = logging.getLogger(__name__)

TALLY_ERROR_KEYWORDS = ['LINEERROR', 'IMPORTERROR', 'ERROR']


class TallyClient:
    """Low-level HTTP client for TallyPrime XML gateway."""

    def __init__(self, url, timeout=30):
        self.url = url
        self.timeout = timeout

    def send(self, xml_payload):
        """
        Send an XML payload to TallyPrime.
        Returns (success: bool, response_text: str, error: str|None)
        """
        try:
            response = requests.post(
                self.url,
                data=xml_payload.encode('utf-8'),
                headers={'Content-Type': 'text/xml; charset=utf-8'},
                timeout=self.timeout,
            )
            response.raise_for_status()
            response_text = response.text
            error = self._parse_tally_error(response_text)
            if error:
                _logger.warning('TallyPrime import error: %s', error)
                return False, response_text, error
            _logger.info('TallyPrime sync successful. Response length: %d chars', len(response_text))
            return True, response_text, None

        except requests.exceptions.ConnectionError as e:
            msg = f'Cannot connect to TallyPrime at {self.url}. Ensure Tally is open.'
            _logger.error('%s — %s', msg, e)
            return False, '', msg
        except requests.exceptions.Timeout:
            msg = f'TallyPrime request timed out after {self.timeout}s.'
            _logger.error(msg)
            return False, '', msg
        except requests.exceptions.HTTPError as e:
            msg = f'TallyPrime HTTP error: {e}'
            _logger.error(msg)
            return False, str(e), msg
        except Exception as e:
            msg = f'Unexpected error communicating with TallyPrime: {e}'
            _logger.exception(msg)
            return False, '', msg

    def _parse_tally_error(self, response_text):
        """
        Parse TallyPrime XML response for error or exception indicators.
        Returns error string if found, None if success.
        """
        try:
            root = ET.fromstring(response_text)

            # 1. Check for LINEERROR tags
            for tag in TALLY_ERROR_KEYWORDS:
                errors = root.findall(f'.//{tag}')
                if errors:
                    err_texts = [e.text for e in errors if e.text]
                    if err_texts:
                        return ' | '.join(err_texts)

            # 2. Check IMPORTRESULT summary
            result = root.find('.//IMPORTRESULT')
            if result is not None:
                exceptions = int(result.findtext('EXCEPTIONS', '0') or 0)
                errors = int(result.findtext('ERRORS', '0') or 0)
                created = int(result.findtext('CREATED', '0') or 0)
                altered = int(result.findtext('ALTERED', '0') or 0)

                if exceptions > 0:
                    return f'Tally rejected entry with {exceptions} exception(s). Check tally.imp file in Tally folder.'
                if errors > 0:
                    return f'Tally import failed with {errors} error(s).'
                if created == 0 and altered == 0:
                    return 'Tally processed request but 0 vouchers were created or altered.'

        except ET.ParseError:
            if any(kw in response_text.upper() for kw in TALLY_ERROR_KEYWORDS):
                return f'Tally returned error response: {response_text[:400]}'

        return None
