"""
``script_json``: print an already-serialised JSON string inside a <script> block.

Several back-office pages build chart data with ``json.dumps`` in the view and
print it with ``|safe``. ``json.dumps`` does not escape ``<``, so a customer or
product name containing ``</script><script>...`` closed the script tag and ran
its own code in the admin's browser. Customers register themselves and product
names are imported from supplier pages, so both are outside our control.

This filter escapes the characters that can break out of a script element, the
same set Django's own ``json_script`` escapes. The result is still valid JSON
and JavaScript, so the page reads exactly the same values.

Usage::

    {% load script_json %}
    var labels = {{ chart_labels|script_json }};
"""

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_ESCAPES = {
    ord('<'): '\\u003C',
    ord('>'): '\\u003E',
    ord('&'): '\\u0026',
    # Line/paragraph separators are legal in JSON strings but were line
    # terminators in older JavaScript engines.
    ord(' '): '\\u2028',
    ord(' '): '\\u2029',
}


@register.filter(is_safe=True)
def script_json(value):
    """Escape a JSON string so it cannot end the surrounding <script> tag."""
    if value is None:
        return mark_safe('null')
    return mark_safe(str(value).translate(_ESCAPES))
