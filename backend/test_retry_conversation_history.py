from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.analytics_service import record_widget_chat_message


@pytest.mark.parametrize('status', ['aborted', 'error'])
def test_retry_restores_question_missing_after_early_abort(status):
    db = Mock()
    bot = SimpleNamespace(organization_id=3)
    message = SimpleNamespace(status=status, user_message=None, assistant_response=None)
    db.query.return_value.filter.return_value = db.query.return_value
    db.query.return_value.first.side_effect = [bot, message]
    with patch('services.analytics_service.consume_message_quota', return_value=True):
        assert record_widget_chat_message(db=db, bot_id=1, session_id='session',
            user_message='How do I use this product?', assistant_response='Source answer',
            response_time_ms=100, client_turn_id='turn', allow_aborted_retry=True,
            usage_reservation_key='reservation')
    assert message.user_message == 'How do I use this product?'
    assert message.status == 'success'
    assert message.assistant_response == 'Source answer'
    db.commit.assert_called_once()


def test_retry_does_not_replace_an_existing_question():
    db = Mock()
    bot = SimpleNamespace(organization_id=3)
    message = SimpleNamespace(status='error', user_message='Original question')
    db.query.return_value.filter.return_value = db.query.return_value
    db.query.return_value.first.side_effect = [bot, message]
    with patch('services.analytics_service.consume_message_quota', return_value=True):
        assert record_widget_chat_message(db=db, bot_id=1, session_id='session',
            user_message='Different text', assistant_response='Source answer',
            response_time_ms=100, client_turn_id='turn', usage_reservation_key='reservation')
    assert message.user_message == 'Original question'
