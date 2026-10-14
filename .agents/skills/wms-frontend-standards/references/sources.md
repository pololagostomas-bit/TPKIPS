# Referencias Verificadas

Consulta: 2026-10-14, America/Bogota. Stars observadas por la API publica GitHub,
no una garantia de seguridad/calidad ni valores que deban repetirse como actuales
sin consultar nuevamente. No se instalaron ni copiaron estas bibliotecas.

| Repositorio | Stars observadas | Licencia comprobada | Uso en nuestro criterio |
| --- | --- | --- | --- |
| [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 135605 | [LICENSE MIT](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/main/LICENSE) | Skill de consulta y MASTER con reglas persistentes; validar ajuste de cada resultado. |
| [Microsoft Fluent UI](https://github.com/microsoft/fluentui) | 20320 | [LICENSE MIT](https://github.com/microsoft/fluentui/blob/master/LICENSE); fuentes/iconos tienen condiciones adicionales. | Jerarquia y composicion adaptable; no copiar assets ni asumir licencia MIT para todo. |
| [Ant Design](https://github.com/ant-design/ant-design) | 99760 | [LICENSE MIT](https://github.com/ant-design/ant-design/blob/master/LICENSE) | Formularios/tablas empresariales y rejilla responsive, no migrar el WMS a React. |

GitHub devolvio NOASSERTION para la clasificacion automatica de licencia de
Fluent UI, pero el archivo LICENSE consultado contiene MIT y una nota separada
para fuentes/iconos. No convertir una etiqueta automatica en prueba concluyente.

## Patrones Que Si Se Adoptan

- [Fluent 2: Layout](https://fluent2.microsoft.design/layout): ajustar composicion
  al espacio disponible y redistribuir lista/detalle y columnas. Los breakpoints
  WMS son propios y preservan el shell, no una copia de sus rangos.
- [Ant Design: Grid](https://ant.design/components/grid/): columnas que se
  reorganizan por ancho y espacios consistentes. Nuestra implementacion sigue
  con Grid/Flex CSS nativo y los componentes existentes.
- [WCAG Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html): conservar
  acceso al estrechar/ampliar; las tablas con significado bidimensional pueden
  requerir su propio desplazamiento. No ocultar overflow globalmente.
- [WCAG Target Size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html):
  el minimo AA de este criterio es 24x24 CSS px o una excepcion admitida. WMS
  elige un objetivo tactil mayor:44px, preferido48px para escaneo.
- [WCAG Focus Not Obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html):
  AA no permite ocultar completamente el foco. WMS busca mantener campo y accion
  criticos enteramente visibles, un criterio de usabilidad propio mas estricto.

## Limites De La Skill Generica

El README upstream presenta un ejemplo before/after de dashboard de operaciones
en su seccion Examples y lo identifica como contribucion comunitaria ilustrativa,
no demo oficial ni benchmark. Se reviso esa descripcion; no se ejecuto ni audito
el sitio comunitario. No usarlo como prueba de rendimiento o de uso empresarial.

Las dos consultas locales `warehouse operations dashboard mobile` e
`internal operations dashboard`, con design-system/densidad8/movimiento1,
retornaron General, reasoning_default=true y una estructura promocional sin
identidad de producto verificada. Se descartaron: no se persistieron sus colores,
fuentes, hero ni animacion. El MASTER es una decision WMS curada desde el codigo
existente y las fuentes oficiales, no una recomendacion generada y validada.

La consulta puntual `focus not obscured --domain ux` si encontro la distincion
AA/AAA correcta y pertinente. Aplicar hallazgos por problema; no regenerar una
identidad visual por cada ajuste. Estos lineamientos no son una certificacion
WCAG ni la promesa de que todas las pantallas existentes ya los cumplen.
