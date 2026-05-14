from django import template

register = template.Library()


@register.filter
def get_item(d, key):
    if isinstance(d, dict):
        return d.get(key)
    return None


@register.filter
def fuel_prix(stats, fuel):
    if not stats:
        return "—"
    val = stats.get(f"{fuel}_prix_moyen")
    return f"{val:.3f}" if val is not None else "—"


@register.filter
def fuel_rupture(stats, fuel):
    if not stats:
        return "—"
    val = stats.get(f"{fuel}_taux_rupture")
    if val is None:
        return "—"
    return f"{val * 100:.1f} %"
