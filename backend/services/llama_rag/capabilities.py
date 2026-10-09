"""Static website data cannot verify live or private account facts."""
import re

def capability_requirement(question: str):
    """Route only literal requests that cannot be answered from a static corpus."""
    q = question.casefold().replace('\u2019', "'")
    # A question about a captured page is a static-evidence request, even if it
    # quotes words such as "today" or "in stock" from that page.
    if re.search(r'\b(?:saved|archived|crawled|captured|snapshot|dataset)\b', q) and re.search(
            r'\b(?:page|website|data|say|said|show|showed|state|stated|report|record)\b', q):
        return None
    if re.search(r'\bwhere (?:is|are|did) (?:my|our) (?:order|package|parcel|shipment)\b', q) or re.search(
            r'^(?:(?:please|can you|could you|will you)\s+)?(?:track|locate|check(?: the)? status of)\s+(?:my|our)\s+(?:order|package|parcel|shipment)\b', q) or re.search(
            r'\b(?:status|location|tracking number) (?:of|for) (?:my|our) (?:order|package|parcel|shipment)\b', q):
        return {'capability': 'private_order_data',
                'reason': 'Order tracking needs access to your order. I can search saved website pages, but cannot access private orders.'}
    live = re.search(r'\b(?:right now|right this (?:minute|second)|currently|today|tomorrow|at the moment|live|current)\b', q)
    if live and re.search(r'\b(?:weather|forecast)\b', q):
        return {'capability': 'live_weather',
                'reason': 'Current weather needs a live weather source. I can only search saved website pages.'}
    if live and re.search(r'\b(?:in stock|out of stock|stock status|stock availability)\b', q) and re.search(
            r'^\s*(?:is|are|do you|does|can you|check|what|which|tell me)\b', q):
        return {'capability': 'live_inventory',
                'reason': 'Current stock needs a live inventory source. A saved product page cannot verify availability right now.'}
    if live and re.search(r'\b(?:discount|coupon|promo)(?:tion)?\s+codes?\b', q) and re.search(
            r'\b(?:work|works|working|valid|active|checkout|use)\b', q):
        return {'capability': 'live_checkout',
                'reason': 'A working checkout code needs live checkout validation. I cannot verify whether a saved offer is active today.'}
    return None


