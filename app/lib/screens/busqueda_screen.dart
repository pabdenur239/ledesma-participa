import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'detalle_screen.dart';
import '../theme.dart';

/// Reutiliza el índice de búsqueda que YA genera y publica el sitio web
/// (docs/assets/search-index.json — mismo archivo que usa la página
/// /buscar/ del sitio) en vez de duplicar lógica de búsqueda nueva: mismo
/// algoritmo (substring, insensible a acentos/mayúsculas) que ya está en
/// producción, ver docs/assets/site.js.
class BusquedaScreen extends StatefulWidget {
  const BusquedaScreen({super.key});

  @override
  State<BusquedaScreen> createState() => _BusquedaScreenState();
}

class _ItemIndice {
  final String titulo;
  final String resumen;
  final String seccion;
  final String fecha;
  final String? imagen;
  final String buscable;
  final int? id;

  _ItemIndice({
    required this.titulo,
    required this.resumen,
    required this.seccion,
    required this.fecha,
    required this.imagen,
    required this.buscable,
    required this.id,
  });

  factory _ItemIndice.fromJson(Map<String, dynamic> json) {
    final url = (json['url'] as String?) ?? '';
    final coincidencia = RegExp(r'noticias/(\d+)-').firstMatch(url);
    return _ItemIndice(
      titulo: (json['titulo'] as String?) ?? '',
      resumen: (json['resumen'] as String?) ?? '',
      seccion: (json['seccion'] as String?) ?? '',
      fecha: (json['fecha'] as String?) ?? '',
      imagen: json['imagen'] as String?,
      buscable: (json['buscable'] as String?) ?? '',
      id: coincidencia != null ? int.tryParse(coincidencia.group(1)!) : null,
    );
  }
}

String _normalizar(String texto) {
  const conAcento = 'áàäâãéèëêíìïîóòöôõúùüûñç';
  const sinAcento = 'aaaaaeeeeiiiiooooouuuunc';
  var resultado = texto.toLowerCase();
  for (var i = 0; i < conAcento.length; i++) {
    resultado = resultado.replaceAll(conAcento[i], sinAcento[i]);
  }
  return resultado;
}

class _BusquedaScreenState extends State<BusquedaScreen> {
  List<_ItemIndice>? _indice;
  List<_ItemIndice> _resultados = [];
  final _controlador = TextEditingController();

  Future<void> _cargarIndice() async {
    if (_indice != null) return;
    final respuesta = await http
        .get(Uri.parse('https://ledesmaparticipa.com.ar/assets/search-index.json'))
        .timeout(const Duration(seconds: 12));
    final datos = jsonDecode(respuesta.body) as List;
    _indice = datos.map((e) => _ItemIndice.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<void> _buscar(String consulta) async {
    final normalizada = _normalizar(consulta.trim());
    if (normalizada.isEmpty) {
      setState(() => _resultados = []);
      return;
    }
    await _cargarIndice();
    final filtrados = _indice!.where((i) => i.buscable.contains(normalizada)).take(40).toList();
    if (mounted) setState(() => _resultados = filtrados);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: TextField(
          controller: _controlador,
          autofocus: true,
          decoration: const InputDecoration(hintText: 'Buscar noticias…', border: InputBorder.none),
          style: const TextStyle(color: Colors.white, fontSize: 16),
          onChanged: _buscar,
        ),
      ),
      body: _resultados.isEmpty
          ? Center(
              child: Text(
                _controlador.text.trim().isEmpty ? 'Escribí para buscar.' : 'Sin resultados.',
                style: const TextStyle(color: MarcaColores.textoSuave),
              ),
            )
          : ListView.builder(
              itemCount: _resultados.length,
              itemBuilder: (context, index) {
                final item = _resultados[index];
                return ListTile(
                  leading: item.imagen != null
                      ? SizedBox(width: 48, height: 48, child: Image.network(item.imagen!, fit: BoxFit.cover))
                      : const Icon(Icons.article_outlined),
                  title: Text(item.titulo, maxLines: 2, overflow: TextOverflow.ellipsis),
                  subtitle: Text('${item.seccion} · ${item.fecha}', maxLines: 1, overflow: TextOverflow.ellipsis),
                  onTap: item.id == null
                      ? null
                      : () => Navigator.of(context).push(
                            MaterialPageRoute(builder: (_) => DetalleScreen(noticiaId: item.id!)),
                          ),
                );
              },
            ),
    );
  }
}
