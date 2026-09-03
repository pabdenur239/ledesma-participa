import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme.dart';

/// Datos de contacto del medio. Solo información pública: no pide ni
/// recolecta ningún dato de quien usa la app (sin formularios, sin
/// registro, sin chat).
class ContactoScreen extends StatelessWidget {
  const ContactoScreen({super.key});

  static const _email = 'ledesmaparticipa@gmail.com';
  static const _sitio = 'https://ledesmaparticipa.com.ar/';
  static const _contactoWeb = 'https://ledesmaparticipa.com.ar/contacto/';

  Future<void> _abrir(String url) async {
    await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Contacto')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Ledesma Participa', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          const Text(
            'Para consultas, correcciones, información, reclamos o contacto '
            'con Ledesma Participa, podés comunicarte a través del correo '
            'indicado.',
            style: TextStyle(fontSize: 15, height: 1.4),
          ),
          const Divider(height: 32),
          _Fila(
            icono: Icons.mail_outline,
            etiqueta: 'Correo',
            valor: _email,
            onTap: () => _abrir('mailto:$_email'),
          ),
          _Fila(
            icono: Icons.public,
            etiqueta: 'Sitio web',
            valor: _sitio,
            onTap: () => _abrir(_sitio),
          ),
          _Fila(
            icono: Icons.contact_page_outlined,
            etiqueta: 'Contacto web',
            valor: _contactoWeb,
            onTap: () => _abrir(_contactoWeb),
          ),
        ],
      ),
    );
  }
}

class _Fila extends StatelessWidget {
  final IconData icono;
  final String etiqueta;
  final String valor;
  final VoidCallback onTap;

  const _Fila({required this.icono, required this.etiqueta, required this.valor, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(icono, color: MarcaColores.marcaOro),
      title: Text(etiqueta, style: const TextStyle(fontSize: 12.5, color: MarcaColores.textoSuave)),
      subtitle: Text(
        valor,
        style: const TextStyle(fontSize: 15, color: MarcaColores.marcaOro, decoration: TextDecoration.underline),
      ),
      onTap: onTap,
    );
  }
}
