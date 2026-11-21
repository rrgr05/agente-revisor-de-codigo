<!-- Ejemplo generado con datos INVENTADOS para enseñar el formato del informe. -->
# Revisión de código — tienda-ejemplo

- **Fecha:** 21-11-2026 17:11
- **Alcance:** proyecto completo
- **Estado:** completa
- **Modelo:** claude-opus-5-5 (especialistas: claude-sonnet-5-5) · esfuerzo high
- **Coste:** 1.87 USD (estimado) · tope 5.00 USD · 6.9 min · 64 turnos
- **Subagentes lanzados:** buenas-practicas, fiabilidad, rendimiento, seguridad, verificador

> Informe generado por el Agente revisor de código. Es de solo lectura: no se ha cambiado nada del proyecto. Los textos los ha escrito una IA: revisa cada hallazgo antes de arreglarlo.

## Resumen

EJEMPLO con datos inventados. El código está bien organizado, pero hay una inyección SQL grave en el catálogo y el listado de pedidos no aguantará cuando crezca.

| Gravedad | Hallazgos |
|---|---|
| 🔴 Crítica | 1 |
| 🟠 Alta | 1 |
| 🟡 Media | 1 |
| 🔵 Baja | 1 |
| **Total** | **4** |

## Lo que está bien hecho

- Las contraseñas se guardan con password_hash.
- Casi todas las consultas están preparadas.

## Índice de hallazgos

| ID | Gravedad | Dónde | Título |
|---|---|---|---|
| [H-001](#h-001) | 🔴 Crítica | `app/Controllers/ProductController.php:42-44` | Consulta SQL construida con el parámetro «id» de la URL |
| [H-002](#h-002) | 🟠 Alta | `app/Services/OrderService.php:88-95` | Una consulta por cada pedido al listar los pedidos |
| [H-003](#h-003) | 🟡 Media | `app/Mail/Mailer.php:31-33` | Los fallos al enviar correos se esconden |
| [H-004](#h-004) | 🔵 Baja | `resources/js/cart.js:120-160` | Cálculo del total del carrito repetido en dos sitios |

## Hallazgos

### H-001

**Consulta SQL construida con el parámetro «id» de la URL**

- **Gravedad:** 🔴 Crítica · **Confianza:** 97 %
- **Dónde:** `app/Controllers/ProductController.php:42-44`
- **Tema:** seguridad / inyeccion-sql

**Qué pasa:** El valor de $_GET['id'] se concatena en la consulta: `"SELECT * FROM products WHERE id = " . $_GET['id']`. No pasa por ninguna validación.

**Impacto:** Cualquier visitante puede leer o borrar datos de la base de datos con una URL preparada.

**Cómo arreglarlo:** Usar la consulta preparada que ya usa el resto del proyecto: `$db-&gt;prepare('SELECT * FROM products WHERE id = ?')-&gt;execute([$id])`.

### H-002

**Una consulta por cada pedido al listar los pedidos**

- **Gravedad:** 🟠 Alta · **Confianza:** 90 %
- **Dónde:** `app/Services/OrderService.php:88-95`
- **Tema:** rendimiento / n+1

**Qué pasa:** Dentro del bucle de pedidos se llama a `findCustomer($order-&gt;customer_id)`, que hace una consulta cada vez. La lista no tiene paginación.

**Impacto:** Con 2.000 pedidos son 2.001 consultas por carga de la página; el servidor se satura.

**Cómo arreglarlo:** Traer los clientes de una vez (`WHERE id IN (...)`) o con un JOIN, y paginar la lista.

### H-003

**Los fallos al enviar correos se esconden**

- **Gravedad:** 🟡 Media · **Confianza:** 88 %
- **Dónde:** `app/Mail/Mailer.php:31-33`
- **Tema:** fiabilidad / excepcion-tragada

**Qué pasa:** `catch (Exception $e) {}` vacío: si el servidor de correo falla, no queda ni rastro.

**Impacto:** Los usuarios no reciben el correo de recuperación y nadie se entera.

**Cómo arreglarlo:** Registrar el error con el logger del proyecto y devolver un aviso al usuario.

### H-004

**Cálculo del total del carrito repetido en dos sitios**

- **Gravedad:** 🔵 Baja · **Confianza:** 80 %
- **Dónde:** `resources/js/cart.js:120-160`
- **Tema:** buenas-practicas / duplicacion

**Qué pasa:** La misma suma de precios, descuentos e impuestos está en `cart.js` y en `checkout.js`.

**Impacto:** Si se cambia una y no la otra, el total del carrito y el del pago no coincidirán.

**Cómo arreglarlo:** Sacar el cálculo a una función común y usarla en los dos archivos.

## Investigado en internet

- **Laravel 12: cambios y buenas prácticas**
  - `https://laravel.com/docs/12.x/upgrade`

## Sin revisar o con dudas

- tests/: no se revisaron las pruebas (fuera del alcance pedido).

## Inventario del proyecto

```text
Raíz del proyecto: /proyectos/tienda-ejemplo
Archivos de código: 214 (unas 18.400 líneas)
Lenguajes: PHP (150), JavaScript (40), SQL (24)
```
