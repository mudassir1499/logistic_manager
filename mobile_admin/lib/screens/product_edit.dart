import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// Create a listing, or edit one, from the phone.
///
/// THE ORDER OF OPERATIONS MATTERS
///
/// A photo and a variation both need a product id, and the product does not
/// have one until it is saved. So a NEW listing saves the row first, then
/// unlocks the photo and variation sections. That is why they are visibly
/// disabled until the first save rather than hidden: hiding them would make the
/// screen look like it cannot do those things at all.
///
/// New listings are created as DRAFTS. A product with no photo is rejected by
/// Meta and TikTok and looks broken on the storefront, and the gap between
/// "saved the row" and "added the picture" is exactly where a half-finished
/// listing would otherwise go live.
class ProductEditScreen extends StatefulWidget {
  const ProductEditScreen({super.key, this.product});

  /// Null when creating.
  final Map<String, dynamic>? product;

  @override
  State<ProductEditScreen> createState() => _ProductEditScreenState();
}

class _ProductEditScreenState extends State<ProductEditScreen> {
  late Map<String, dynamic>? _product = widget.product;

  late final _name = TextEditingController(text: '${_product?['name'] ?? ''}');
  late final _sku = TextEditingController(text: '${_product?['sku'] ?? ''}');
  late final _price = TextEditingController(text: '${_product?['price'] ?? ''}');
  late final _moq = TextEditingController(text: '${_product?['moq'] ?? '1'}');
  late final _weight = TextEditingController(text: '${_product?['weight'] ?? ''}');
  late final _cartonQty =
      TextEditingController(text: '${_product?['carton_qty'] ?? ''}');

  String? _category;
  List<Map<String, dynamic>> _categories = [];
  List<Map<String, dynamic>> _images = [];
  List<Map<String, dynamic>> _variants = [];
  bool _busy = false;
  bool _dirty = false;

  bool get _isNew => _product == null;
  String? get _slug => _product?['slug'] as String?;
  int? get _id => _product?['id'] as int?;

  @override
  void initState() {
    super.initState();
    _category = _product?['category'] as String?;
    _loadCategories();
    if (!_isNew) _refreshChildren();
  }

  @override
  void dispose() {
    for (final c in [_name, _sku, _price, _moq, _weight, _cartonQty]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadCategories() async {
    try {
      final rows = await Api.instance.categories();
      if (mounted) setState(() => _categories = rows);
    } catch (_) {
      // A missing category list is survivable — the field is optional — so it
      // must not block the whole form behind an error.
    }
  }

  Future<void> _refreshChildren() async {
    if (_slug == null) return;
    try {
      final fresh = await Api.instance.product(_slug!);
      final vars = await Api.instance.variants(_id!);
      if (!mounted) return;
      setState(() {
        _product = fresh;
        _images = List<Map<String, dynamic>>.from(
            (fresh['images'] as List?) ?? const []);
        _variants = vars;
      });
    } catch (_) {}
  }

  Map<String, dynamic> _fields() => {
        'name': _name.text.trim(),
        'sku': _sku.text.trim(),
        'price': _price.text.trim(),
        'moq': int.tryParse(_moq.text.trim()) ?? 1,
        if (_weight.text.trim().isNotEmpty) 'weight': _weight.text.trim(),
        if (_cartonQty.text.trim().isNotEmpty)
          'carton_qty': int.tryParse(_cartonQty.text.trim()),
        if (_category != null) 'category': _category,
      };

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      toast(context, 'A listing needs a name.', error: true);
      return;
    }
    if ((double.tryParse(_price.text.trim()) ?? 0) <= 0) {
      toast(context, 'Enter a price greater than zero.', error: true);
      return;
    }

    setState(() => _busy = true);
    try {
      if (_isNew) {
        // Draft until it has a photo — see the class comment.
        final created = await Api.instance
            .createProduct({..._fields(), 'is_draft': true});
        setState(() { _product = created; _dirty = true; });
        if (mounted) {
          toast(context, 'Draft created — now add a photo');
        }
      } else {
        final updated = await Api.instance.updateProduct(_slug!, _fields());
        setState(() { _product = updated; _dirty = true; });
        if (mounted) toast(context, 'Saved');
      }
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addPhoto(ImageSource source) async {
    final picked = await ImagePicker().pickImage(
      source: source,
      // Resized on the device rather than the server: it saves the upload, not
      // just the disk. The storefront never renders above ~1000px anyway.
      maxWidth: 1600,
      imageQuality: 85,
    );
    if (picked == null || _id == null) return;

    setState(() => _busy = true);
    final ok = await runWrite(
      context,
      () => Api.instance.uploadProductImage(_id!, picked.path),
      success: 'Photo added',
    );
    if (mounted) setState(() { _busy = false; _dirty = true; });
    if (ok) await _refreshChildren();
  }

  Future<void> _removePhoto(int imageId) async {
    final ok = await runWrite(
        context, () => Api.instance.deleteProductImage(imageId),
        success: 'Photo removed');
    if (ok) { _dirty = true; await _refreshChildren(); }
  }

  Future<void> _editVariant([Map<String, dynamic>? variant]) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _VariantSheet(productId: _id!, variant: variant),
    );
    if (saved == true) { _dirty = true; await _refreshChildren(); }
  }

  Future<void> _publish() async {
    if (_images.isEmpty) {
      toast(context,
          'Add a photo first — a listing without one is rejected by Meta and TikTok.',
          error: true);
      return;
    }
    final ok = await runWrite(
        context, () => Api.instance.updateProduct(_slug!, {'is_draft': false}),
        success: 'Published');
    if (ok) { _dirty = true; await _refreshChildren(); }
  }

  @override
  Widget build(BuildContext context) {
    final isDraft = _product?['is_draft'] == true;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) Navigator.pop(context, _dirty);
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(_isNew ? 'New listing' : 'Edit listing'),
          actions: [
            if (!_isNew && isDraft)
              TextButton(
                onPressed: _busy ? null : _publish,
                child: const Text('Publish',
                    style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
              ),
          ],
        ),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (!_isNew && isDraft)
              Container(
                margin: const EdgeInsets.only(bottom: 14),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Brand.warn.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Brand.warn.withValues(alpha: 0.35)),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.info_outline, size: 18, color: Brand.warn),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'This is a draft. Customers cannot see it until you publish.',
                        style: TextStyle(fontSize: 12.5, color: Brand.warn),
                      ),
                    ),
                  ],
                ),
              ),

            SectionCard(
              title: 'Basics',
              child: Column(
                children: [
                  TextField(
                      controller: _name,
                      textCapitalization: TextCapitalization.sentences,
                      decoration: const InputDecoration(
                          labelText: 'Product name',
                          hintText: '65W GaN Fast Charger Type-C')),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                            controller: _price,
                            keyboardType:
                                const TextInputType.numberWithOptions(decimal: true),
                            decoration: const InputDecoration(labelText: 'Price')),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: TextField(
                            controller: _moq,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(labelText: 'MOQ')),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  TextField(
                      controller: _sku,
                      autocorrect: false,
                      decoration: const InputDecoration(
                          labelText: 'SKU', hintText: 'Leave blank to auto-generate')),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: _categories.any((c) => c['slug'] == _category)
                        ? _category
                        : null,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Category'),
                    items: _categories
                        .map((c) => DropdownMenuItem(
                            value: '${c['slug']}',
                            child: Text('${c['name']}',
                                overflow: TextOverflow.ellipsis)))
                        .toList(),
                    onChanged: (v) => setState(() => _category = v),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),

            SectionCard(
              title: 'Shipping',
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                        controller: _weight,
                        keyboardType:
                            const TextInputType.numberWithOptions(decimal: true),
                        decoration: const InputDecoration(labelText: 'Weight (kg)')),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                        controller: _cartonQty,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(labelText: 'Pcs/carton')),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),

            FilledButton(
              onPressed: _busy ? null : _save,
              child: Text(_busy
                  ? 'Saving…'
                  : (_isNew ? 'Create draft' : 'Save changes')),
            ),
            const SizedBox(height: 20),

            // --- photos, unlocked once the row exists ---
            Opacity(
              opacity: _isNew ? 0.45 : 1,
              child: IgnorePointer(
                ignoring: _isNew,
                child: SectionCard(
                  title: 'Photos (${_images.length}/3)',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (_isNew)
                        const Text('Save the listing first, then add photos.',
                            style: TextStyle(fontSize: 12.5, color: Brand.muted))
                      else if (_images.isEmpty)
                        const Text(
                            'No photos yet. Meta and TikTok reject items without one.',
                            style: TextStyle(fontSize: 12.5, color: Brand.warn)),
                      if (_images.isNotEmpty)
                        SizedBox(
                          height: 92,
                          child: ListView.separated(
                            scrollDirection: Axis.horizontal,
                            itemCount: _images.length,
                            separatorBuilder: (_, _) => const SizedBox(width: 8),
                            itemBuilder: (_, i) {
                              final img = _images[i];
                              return Stack(
                                children: [
                                  ClipRRect(
                                    borderRadius: BorderRadius.circular(8),
                                    child: Image.network('${img['url']}',
                                        width: 92, height: 92, fit: BoxFit.cover,
                                        errorBuilder: (_, _, _) => Container(
                                            width: 92,
                                            height: 92,
                                            color: Brand.bg,
                                            child: const Icon(
                                                Icons.broken_image_outlined))),
                                  ),
                                  Positioned(
                                    top: 0,
                                    right: 0,
                                    child: InkWell(
                                      onTap: () => _removePhoto(img['id'] as int),
                                      child: Container(
                                        decoration: const BoxDecoration(
                                            color: Brand.danger,
                                            shape: BoxShape.circle),
                                        padding: const EdgeInsets.all(3),
                                        child: const Icon(Icons.close,
                                            size: 13, color: Colors.white),
                                      ),
                                    ),
                                  ),
                                ],
                              );
                            },
                          ),
                        ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: (_busy || _images.length >= 3)
                                  ? null
                                  : () => _addPhoto(ImageSource.camera),
                              icon: const Icon(Icons.photo_camera_outlined),
                              label: const Text('Camera'),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: (_busy || _images.length >= 3)
                                  ? null
                                  : () => _addPhoto(ImageSource.gallery),
                              icon: const Icon(Icons.photo_library_outlined),
                              label: const Text('Gallery'),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 14),

            // --- variations ---
            Opacity(
              opacity: _isNew ? 0.45 : 1,
              child: IgnorePointer(
                ignoring: _isNew,
                child: SectionCard(
                  title: 'Variations (${_variants.length})',
                  trailing: _isNew
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.add, size: 20),
                          onPressed: () => _editVariant(),
                        ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (_isNew)
                        const Text('Save the listing first, then add variations.',
                            style: TextStyle(fontSize: 12.5, color: Brand.muted))
                      else if (_variants.isEmpty)
                        const Text(
                            'No variations. The listing sells at its own price.',
                            style: TextStyle(fontSize: 12.5, color: Brand.muted)),
                      ..._variants.map((v) => ListTile(
                            contentPadding: EdgeInsets.zero,
                            dense: true,
                            title: Text('${v['name']}'),
                            subtitle: Text(money(v['price'])),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.edit_outlined, size: 18),
                                  onPressed: () => _editVariant(v),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.delete_outline,
                                      size: 18, color: Brand.danger),
                                  onPressed: () async {
                                    final ok = await runWrite(
                                        context,
                                        () => Api.instance
                                            .deleteVariant(v['id'] as int),
                                        success: 'Variation retired');
                                    if (ok) await _refreshChildren();
                                  },
                                ),
                              ],
                            ),
                          )),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 30),
          ],
        ),
      ),
    );
  }
}

class _VariantSheet extends StatefulWidget {
  const _VariantSheet({required this.productId, this.variant});
  final int productId;
  final Map<String, dynamic>? variant;
  @override
  State<_VariantSheet> createState() => _VariantSheetState();
}

class _VariantSheetState extends State<_VariantSheet> {
  late final _name =
      TextEditingController(text: '${widget.variant?['name'] ?? ''}');
  late final _price =
      TextEditingController(text: '${widget.variant?['price'] ?? ''}');
  late final _stock =
      TextEditingController(text: '${widget.variant?['stock'] ?? ''}');
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _price.dispose();
    _stock.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      toast(context, 'Give the variation a name.', error: true);
      return;
    }
    setState(() => _busy = true);
    final ok = await runWrite(
      context,
      () => Api.instance.saveVariant({
        'product': widget.productId,
        'name': _name.text.trim(),
        'price': _price.text.trim(),
        // Empty means "not tracked", which is not the same as zero — the ad
        // feed reads an explicit 0 as out of stock.
        'stock': _stock.text.trim().isEmpty
            ? null
            : int.tryParse(_stock.text.trim()),
      }, id: widget.variant?['id'] as int?),
      success: widget.variant == null ? 'Variation added' : 'Variation saved',
    );
    if (mounted) setState(() => _busy = false);
    if (ok && mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 16, right: 16, top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(widget.variant == null ? 'Add variation' : 'Edit variation',
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 16),
          TextField(
              controller: _name,
              autofocus: true,
              decoration: const InputDecoration(
                  labelText: 'Name', hintText: 'Blue / 40oz')),
          const SizedBox(height: 12),
          TextField(
              controller: _price,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Price')),
          const SizedBox(height: 12),
          TextField(
              controller: _stock,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: 'Stock', hintText: 'Leave blank if not tracked')),
          const SizedBox(height: 18),
          FilledButton(
              onPressed: _busy ? null : _save,
              child: Text(_busy ? 'Saving…' : 'Save')),
        ],
      ),
    );
  }
}
