"""
utils/llm.py

Server-side Claude integration for the 1688 product-sourcing extension.

WHY THIS RUNS ON THE SERVER RATHER THAN IN THE EXTENSION:
    A Chrome extension's files are readable by anyone who installs it, so an
    Anthropic API key shipped inside one is a published key. The extension
    therefore posts the scraped page to Django, and Django calls Anthropic with
    the key from .env. The extension never sees it.

    The extension's other two modes need no server at all: 'none' (pure DOM
    scraping) and 'ollama' (a local model on the user's own machine). This
    module is only reached when the user selects the 'server' mode.

WHAT THE MODEL IS ASKED TO DO:
    1688 listings are Chinese, and their prices are tiered ("阶梯价"): a lower
    unit price as the order quantity rises. The DOM scraper in the extension
    finds what it can, but supplier markup is inconsistent and the layout
    changes often. Claude reads the raw page text and returns a normalised
    record: an English product name, the price tiers as numbers, the unit weight
    in kilograms, and a category chosen from this catalogue's own taxonomy.

    The response is constrained with structured outputs (a JSON schema), so the
    result parses without any defensive string-scraping of the reply.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# The model this project calls. Claude Opus 5 handles Chinese-to-English product
# naming and messy spec tables well, and its per-call cost here is small because
# the input is one page of text and the output is a short JSON record.
CLAUDE_MODEL = 'claude-opus-5'

# Effort trades thinking depth against cost and latency. Extraction is not an
# intelligence-sensitive task and Opus 5 is strong at the low end, so 'low' is
# the default; override with EXTENSION_AI_EFFORT if a supplier's pages prove
# hard to read.
CLAUDE_EFFORT = os.environ.get('EXTENSION_AI_EFFORT', 'low').strip() or 'low'

# Generous relative to the ~400-token JSON reply. On Claude Opus 5 thinking is
# on by default and max_tokens caps thinking PLUS the reply, so a tight limit
# here would truncate the JSON mid-object.
CLAUDE_MAX_TOKENS = 8000


class LLMNotConfigured(RuntimeError):
    """Raised when server-side extraction is requested without an API key."""


class LLMExtractionError(RuntimeError):
    """Raised when the model could not be reached or declined the request."""


# ---------------------------------------------------------------------------
# RESPONSE SCHEMA
# ---------------------------------------------------------------------------
# Passed to the API as output_config.format, which constrains the reply to
# valid JSON matching this shape. Every object sets additionalProperties: false
# and lists every key in `required` — both are required by structured outputs.
#
# Nullable fields are expressed as a two-entry `type` list rather than being
# left out of `required`, so the model must decide explicitly rather than
# silently omitting a field we would then have to treat as unknown.
EXTRACTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'name_en': {
            'type': 'string',
            'description': (
                'Concise English product name suitable for a wholesale '
                'catalogue, 3-10 words. Translate from Chinese. Do not include '
                'supplier names, promotional words, or quantity claims.'
            ),
        },
        'name_original': {
            'type': 'string',
            'description': 'The original product title exactly as shown on the page.',
        },
        'tiers': {
            'type': 'array',
            'description': (
                'Quantity price ladder. One entry per tier shown on the page. '
                'If the page shows a single price with no ladder, return one '
                'entry using the minimum order quantity.'
            ),
            'items': {
                'type': 'object',
                'properties': {
                    'min_qty': {
                        'type': 'integer',
                        'description': 'Smallest quantity this tier applies to.',
                    },
                    'price_rmb': {
                        'type': 'number',
                        'description': 'Unit price in RMB at this tier, excluding shipping.',
                    },
                },
                'required': ['min_qty', 'price_rmb'],
                'additionalProperties': False,
            },
        },
        'moq': {
            'type': ['integer', 'null'],
            'description': 'Supplier minimum order quantity (起订量), or null if not shown.',
        },
        'weight_kg': {
            'type': ['number', 'null'],
            'description': (
                'Weight of ONE piece in kilograms. Convert from grams (克/g) or '
                'catties (斤 = 0.5kg) if needed. Null if the page does not state it. '
                'Do not guess from the product type.'
            ),
        },
        'carton_qty': {
            'type': ['integer', 'null'],
            'description': 'Pieces per carton (箱规/装箱数), or null if not shown.',
        },
        'variations': {
            'type': 'array',
            'description': (
                'One entry per SKU variation listed under "VARIATIONS" in the '
                'user message, in the SAME ORDER, translating each name. Return '
                'an empty array when no variations were supplied. Do not invent, '
                'merge, reorder, or drop entries — the caller matches these back '
                'to the scraped rows by position.'
            ),
            'items': {
                'type': 'object',
                'properties': {
                    'name_original': {
                        'type': 'string',
                        'description': 'The variation name exactly as supplied.',
                    },
                    'name_en': {
                        'type': 'string',
                        'description': (
                            'Short English name for this variation, 2-8 words. '
                            'Keep the distinguishing detail (colour, capacity, '
                            'voltage, which part it is) — that is the only thing '
                            'separating it from its siblings.'
                        ),
                    },
                },
                'required': ['name_original', 'name_en'],
                'additionalProperties': False,
            },
        },
        'category_slug': {
            'type': ['string', 'null'],
            'description': (
                'Best-matching category slug from the provided taxonomy, or null '
                'if none is a reasonable fit. Must be copied exactly from the list.'
            ),
        },
        'subcategory_slug': {
            'type': ['string', 'null'],
            'description': (
                'Best-matching subcategory slug within the chosen category, or '
                'null. Must be copied exactly from the list.'
            ),
        },
        'confidence': {
            'type': 'string',
            'enum': ['high', 'medium', 'low'],
            'description': (
                'How reliable this extraction is. Use "low" when the price ladder '
                'or weight had to be inferred rather than read directly.'
            ),
        },
        'notes': {
            'type': 'string',
            'description': (
                'One short sentence for the operator about anything ambiguous, '
                'or an empty string when the page was unambiguous.'
            ),
        },
    },
    'required': [
        'name_en', 'name_original', 'tiers', 'moq', 'weight_kg',
        'carton_qty', 'variations', 'category_slug', 'subcategory_slug',
        'confidence', 'notes',
    ],
    'additionalProperties': False,
}


SYSTEM_PROMPT = """You extract structured product data from Chinese wholesale \
marketplace pages (1688.com, Taobao, Alibaba) for a sourcing agency that resells \
into the UAE.

Read the supplied page text and return the product's details.

Rules:
- Prices are in RMB (¥ / 元) and EXCLUDE shipping. Never add shipping or markup — \
the caller applies its own markup afterwards.
- 1688 lists tiered pricing (阶梯价): a lower unit price at higher quantities, \
shown as ranges like "2-99件 ¥12.50" or "≥500件 ¥9.80". Return every tier.
- Weight fields are labelled 重量 / 毛重 (gross) / 净重 (net) / 克重. Prefer the \
per-piece weight. 1斤 = 0.5kg, 1克 = 0.001kg.
- Only report a weight the page actually states. A wrong weight produces a wrong \
freight quote, so null is far better than a guess.
- The English name is for a product catalogue: describe the item, not the listing. \
Drop supplier names, "包邮", "厂家直销", and similar promotional text.
- Choose a category only from the taxonomy given in the user message, copying the \
slug exactly. Return null rather than inventing one.
- A listing often sells several SKU variations (颜色分类 / 规格), each with its own \
price. When the user message lists them, translate every one, in the same order, \
keeping whatever distinguishes it from its siblings (colour, capacity, voltage, or \
which part of a set it is). These become separate catalogue products, so a name \
that does not say which variation it is would be useless."""


def _build_user_prompt(page, taxonomy):
    """
    Assemble the user turn: the taxonomy to choose from, then the page content.

    Args:
        page (dict): Scraped page data from the extension — 'url', 'title',
            'text' (visible page text), and optionally 'spec_text'/'price_text'
            where the DOM scraper isolated those regions.
        taxonomy (list[dict]): ``[{'slug', 'name', 'subcategories': [...]}]``.

    Returns:
        str: The prompt text.

    The page text is truncated because a 1688 page carries a long tail of
    recommendations, reviews, and boilerplate that adds tokens without adding
    signal — everything that matters sits near the top.
    """
    lines = ['# Available categories', '']
    for category in taxonomy:
        lines.append(f"- {category['slug']} — {category['name']}")
        for sub in category.get('subcategories', []):
            lines.append(f"    - {sub['slug']} — {sub['name']}")

    lines += ['', '# Product page', '', f"URL: {page.get('url', '')}", '']

    if page.get('title'):
        lines += [f"Title: {page['title']}", '']

    # These two are passed separately when the DOM scraper managed to isolate
    # them, so the model sees the important regions even if the truncation below
    # cuts into the main body.
    if page.get('price_text'):
        lines += ['## Price area', page['price_text'][:2000], '']
    if page.get('spec_text'):
        lines += ['## Specifications area', page['spec_text'][:4000], '']

    # Passed separately and labelled loudly: these names are the text that most
    # needs translating, and they are trivially lost inside a 12,000-character
    # page dump.
    if page.get('variation_text'):
        lines += ['## VARIATIONS (translate every line, same order)',
                  page['variation_text'][:3000], '']

    body = (page.get('text') or '')[:12000]
    lines += ['## Page text', body]

    return '\n'.join(lines)


def _client():
    """
    Build an Anthropic client, or explain why we cannot.

    Raises:
        LLMNotConfigured: when the SDK is not installed or no key is set.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise LLMNotConfigured(
            'The anthropic package is not installed. Run: pip install anthropic'
        ) from exc

    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        raise LLMNotConfigured(
            'ANTHROPIC_API_KEY is not set in the environment or .env file. '
            'Set it, or switch the extension to Ollama or DOM-only mode.'
        )

    return anthropic.Anthropic(api_key=api_key)


def extract_product(page, taxonomy):
    """
    Ask Claude to read a scraped marketplace page and return structured fields.

    Args:
        page (dict): Scraped page data (see ``_build_user_prompt``).
        taxonomy (list[dict]): The catalogue's categories and subcategories.

    Returns:
        dict: Parsed JSON matching EXTRACTION_SCHEMA.

    Raises:
        LLMNotConfigured: No API key or SDK.
        LLMExtractionError: The request failed, or the model declined it.
    """
    client = _client()

    try:
        # The beta endpoint is used for one reason: the `fallbacks` parameter.
        # Claude Opus 5 runs safety classifiers that occasionally decline benign
        # requests; "default" re-runs a declined request on Anthropic's
        # recommended substitute model server-side, inside the same call, so a
        # false positive does not surface to the operator as a failed scrape.
        response = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
            system=SYSTEM_PROMPT,
            # Adaptive thinking lets the model decide how much reasoning a given
            # page needs — a clean listing gets almost none, a messy one more.
            thinking={'type': 'adaptive'},
            output_config={
                'effort': CLAUDE_EFFORT,
                'format': {'type': 'json_schema', 'schema': EXTRACTION_SCHEMA},
            },
            messages=[{
                'role': 'user',
                'content': _build_user_prompt(page, taxonomy),
            }],
        )
    except Exception as exc:
        logger.exception('Claude extraction request failed')
        raise LLMExtractionError(f'Could not reach Claude: {exc}') from exc

    # Check the stop reason BEFORE touching content. On a refusal the content
    # list is empty (declined before any output) or holds a partial answer —
    # indexing into it blindly would raise IndexError or return half a record.
    if response.stop_reason == 'refusal':
        category = getattr(getattr(response, 'stop_details', None), 'category', None)
        raise LLMExtractionError(
            'Claude declined to process this page'
            + (f' (category: {category})' if category else '')
            + '. Try the Ollama or DOM-only extraction mode for this product.'
        )

    text = next((b.text for b in response.content if b.type == 'text'), '')
    if not text:
        raise LLMExtractionError('Claude returned an empty response.')

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Structured outputs make this close to impossible, but a truncated
        # reply (max_tokens exhausted by thinking) would land here.
        raise LLMExtractionError(
            f'Claude returned malformed JSON: {exc}'
        ) from exc

    data['_usage'] = {
        'input_tokens': response.usage.input_tokens,
        'output_tokens': response.usage.output_tokens,
        'model': response.model,
    }
    return data
