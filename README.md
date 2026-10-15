# Sistema de Retroalimentación para RCP

Sistema de entrenamiento y evaluación de compresiones torácicas (RCP) basado en un ESP32 y una aplicación móvil en Flutter, conectados por Bluetooth Low Energy (BLE).

El dispositivo mide la profundidad y la frecuencia de las compresiones en tiempo real, da retroalimentación visual mediante una tira de LEDs, y envía los datos a la app, que califica la sesión de acuerdo a las guías de la AHA 2020.

---

## Cómo funciona

```
        Persona realizando RCP
                  │
                  ▼
        Maniquí / sistema físico
                  │
                  ▼
        Sensor VL6180X (distancia)
                  │
                  ▼
              ESP32
        (MicroPython + aioble)
           │            │
           │            ▼
           │      Tira NeoPixel
           │      (verde/rojo)
           ▼
             BLE
              │
              ▼
         App Flutter
              │
              ▼
      Resultados de la sesión
```

El ESP32 lee la distancia del sensor 20 veces por segundo, detecta cada compresión (inicio, pico y liberación), calcula la profundidad en centímetros y las compresiones por minuto, y lo notifica por BLE. La app recibe esos datos, los muestra en vivo, y al terminar la sesión genera una calificación.

### Parámetros que evalúa

| Parámetro | Rango objetivo |
|---|---|
| Profundidad de compresión | 5 – 6 cm |
| Frecuencia | 100 – 120 cpm |
| Duración de la sesión | 60 segundos |
| Relación compresiones:ventilaciones | 30:2 |

### Modos

- **Entrenamiento**: activa el metrónomo sonoro (100 cpm) y la retroalimentación de LEDs — verde si la profundidad es correcta, rojo si no.
- **Evaluación**: sin ayudas. Solo mide y califica al final.

---

## Material necesario

### Hardware

| Componente | Notas |
|---|---|
| ESP32 | Cualquier placa de desarrollo estándar |
| Sensor VL6180X | Sensor de distancia Time-of-Flight (I2C) |
| 2 Tiras y Aro NeoPixel | 32 LEDs en la configuración actual |
| Mini 360 | Para bajar el voltaje del portapilas |
| Portapilas para 4 pilas AA de 1,5V | Alimentación de los neopixels |
| Cable USB | Para programar y alimentar el ESP32 |
| Maniquí o estructura de pruebas | Donde se monta el sensor |

### Conexiones

| Componente | Pin del ESP32 |
|---|---|
| NeoPixel (datos) | GPIO 27 mas resistencia 330 ohms|
| VL6180X — SCL | GPIO 18 |
| VL6180X — SDA | GPIO 19 |

> El sensor VL6180X se comunica por I2C a 400 kHz. La distancia base (sin compresión) está calibrada en 70 mm; si montas el sensor a otra altura, hay que ajustar la constante `BASE_MM` en el firmware.

---

## Parte 1 — Preparar el ESP32

### 1.1 Instalar Thonny

Descarga e instala Thonny desde [thonny.org](https://thonny.org). Es el editor que se usa para cargar el código al ESP32 y ver la consola serial.

### 1.2 Instalar el driver USB

El ESP32 necesita un driver para que la computadora lo reconozca como puerto serial. Depende del chip que traiga tu placa:

- **CP2102** → driver de Silicon Labs (CP210x VCP Drivers) https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers?tab=downloads


Si no sabes cuál tienes, conecta el ESP32 y revisa el Administrador de dispositivos de Windows: aparecerá el nombre del chip o un dispositivo desconocido que te dará la pista.

### 1.3 Instalar MicroPython (archivo .bin)

1. Descarga el firmware de MicroPython para ESP32 desde [micropython.org/download/esp32](archivo `.bin`) https://micropython.org/download/ESP32_GENERIC/
2. En Thonny, ve a **Herramientas → Opciones → Intérprete**.
3. Selecciona **MicroPython (ESP32)** y tu puerto COM.
4. Da clic en **Instalar o actualizar MicroPython**.
5. Selecciona el archivo `.bin` que descargaste y dale a instalar.

### 1.4 Instalar las librerías en el ESP32

Se necesitan dos librerías dentro del ESP32:

**aioble** (Bluetooth) — desde la consola de Thonny (REPL), con el ESP32 conectado a WiFi:

```python
import mip
mip.install("aioble")
```

Si no tienes WiFi en el ESP32, puedes descargar los archivos de `aioble` del repositorio [micropython-lib](https://github.com/micropython/micropython-lib) y copiarlos manualmente a la placa desde Thonny.

**vl6180x** (sensor de distancia) — descarga el archivo `vl6180x.py` de una librería de MicroPython para este sensor y cópialo a la raíz del ESP32 usando Thonny (**Archivo → Guardar como… → dispositivo MicroPython**).

### 1.5 Cargar el programa principal

1. Abre el archivo del firmware ESP32 en Thonny.
2. Guárdalo en el ESP32 con el nombre **`main.py`** — así se ejecuta automáticamente cada vez que se enciende la placa.
3. Reinicia el ESP32. En la consola debe aparecer `VL6180X listo`.

A partir de ese momento el ESP32 se anuncia por BLE con el nombre **`ESP32-Noemi`** y queda esperando conexión.

---

## Parte 2 — Para editar la app desde tu computadora (Si no es necesario pasar a la parte 4)

### 2.1 Instalar Flutter

1. Descarga el SDK desde [docs.flutter.dev/get-started/install](https://docs.flutter.dev/get-started/install).
2. Extrae el zip en una ruta simple, sin espacios ni acentos (por ejemplo `C:\src\flutter`).
3. Agrega `C:\src\flutter\bin` a la variable de entorno **Path** de Windows.
4. Reinicia la terminal y verifica con `flutter doctor`.

### 2.2 Instalar Android Studio

Aunque el desarrollo se haga en VS Code, Android Studio es necesario porque trae el Android SDK, las platform-tools (`adb`) y las licencias.

Después de instalarlo, corre:

```bash
flutter doctor --android-licenses
```

y acepta todas las licencias.

### 2.3 Instalar Java JDK 17

Las versiones recientes de Android Studio incluyen un Java demasiado nuevo para el Gradle de este proyecto. Instala **Eclipse Temurin JDK 17** desde [adoptium.net](https://adoptium.net) y configúralo:

```bash
flutter config --jdk-dir="C:\Program Files\Eclipse Adoptium\jdk-17.x.x.x-hotspot"
```

Ajusta la ruta a la versión que te haya quedado instalada.

### 2.4 Activar el Modo Desarrollador de Windows

Los plugins de Flutter necesitan permisos de symlink. Abre la configuración con:

```bash
start ms-settings:developers
```

y activa **Modo de desarrollador**.

### 2.5 Instalar la extensión de Flutter en VS Code

Busca "Flutter" en la pestaña de extensiones (Ctrl+Shift+X) e instala la oficial de Dart-Code.

---

## Parte 3 — Correr la aplicación

### 3.1 Clonar y preparar el proyecto

```bash
git clone https://github.com/noemimiroslava/Sistema-de-Retroalimentaci-n-CPR.git
cd Sistema-de-Retroalimentaci-n-CPR
flutter pub get
```

### 3.2 Preparar el teléfono Android

1. **Ajustes → Acerca del teléfono** → toca 7 veces sobre *Número de compilación*.
2. **Ajustes → Opciones de desarrollador** → activa **Depuración USB**.
3. En teléfonos Samsung recientes, si la depuración USB aparece bloqueada: ve a **Ajustes → Seguridad y privacidad → Bloqueador automático** y desactiva el bloqueo de comandos por USB.
4. Conecta el teléfono por cable y acepta el aviso de confianza.

> **Importante:** el Bluetooth BLE no funciona en emuladores. Se necesita un teléfono o tablet físico.

### 3.3 Ejecutar

```bash
flutter devices    # confirma que aparece tu dispositivo
flutter run        # compila e instala la app
```

---

## Parte 4 Descargar e instalar la APP en el telefono

📱 **[Descargar APK (Android)](https://github.com/noemimiroslava/Sistema-de-Retroalimentaci-n-CPR/releases/tag/app )**

> Requiere Android 8.0 o superior. Al instalar, Android pedirá permitir la
> instalación desde fuentes desconocidas. En teléfonos Samsung puede ser
> necesario desactivar el Bloqueador automático.
>
> La app necesita un ESP32 con el firmware de este repositorio para funcionar.

## Parte 5 — Conexión de los neopixeles

1. Conecta el portapilas con interruptor ON/OFF al IN + y IN - del mini 360.
2. Configura la salida OUT + y OUT - del mini 360 a 4.2 V.
3. Conecta en paralelo el VCC y GND de los neopixeles.
4. Conecta el VCC al OUT + y el GND al OUT - del mini 360.
5. Conecta en serie la salida del GPIO 27 junto con una resistencia a la primera entrada en los DIN y DOUT de los neopixesles.
6. Conecta el GND de los neopixeles con el GND de la ESP32.

## Parte 6 — Usar el sistema

1. Enciende el interruptor del portapilas que alimenta a los neopixeles.
2. Conecta el ESP32. La consola muestra `VL6180X listo` y la placa queda anunciándose por BLE.
3. Enciende el Bluetooth del teléfono.
4. Abre la app y presiona **Conectar**. Concede el permiso de *dispositivos cercanos* cuando lo pida.
5. Elige el modo: **Evaluación** o **Entrenamiento**.
6. Comienza las compresiones. La sesión arranca automáticamente con la primera compresión detectada y dura 60 segundos.
7. Al terminar aparece el resumen con la calificación, y la sesión se guarda en el historial (últimas 5 sesiones).

---

## Detalles técnicos del BLE

| Elemento | UUID | Dirección |
|---|---|---|
| Servicio | `19b10002-e8f2-537e-4f6c-d104768a1214` | — |
| Profundidad | `19b10003-e8f2-537e-4f6c-d104768a1214` | notify (float32) |
| Pico + CPM | `19b10004-e8f2-537e-4f6c-d104768a1214` | notify (2× float32) |
| Modo | `19b10005-e8f2-537e-4f6c-d104768a1214` | write (`TRAIN` / `EVAL`) |

Los valores flotantes van en formato little-endian.

---

## Dependencias de la app

| Paquete | Uso |
|---|---|
| `flutter_blue_plus` | Comunicación BLE |
| `permission_handler` | Permisos de Android |
| `provider` | Manejo de estado |
| `syncfusion_flutter_gauges` | Gráficas circulares y medidores |
| `just_audio` | Metrónomo en modo entrenamiento |
| `shared_preferences` | Historial de sesiones |

---

## Solución de problemas

**La app se queda en "Buscando BLE…" y no encuentra el ESP32**

- Verifica que el ESP32 esté encendido y que la consola de Thonny no muestre errores.
- Si el ESP32 aparece vinculado en los ajustes de Bluetooth del sistema, desvincúlalo — la app maneja la conexión por su cuenta.
- Android limita los escaneos si se hacen muchos seguidos. Apaga y enciende el Bluetooth del teléfono y espera un minuto antes de reintentar.

**Thonny dice "Device is busy or does not respond"**

Es normal: significa que el ESP32 está corriendo `main.py`. Usa Ctrl+C para interrumpirlo si necesitas la consola.

**Errores de versión de Gradle, AGP o Kotlin al compilar**

Corre `flutter analyze --suggestions` para ver qué versiones pide tu instalación de Flutter, y ajústalas en `android/settings.gradle.kts` y `android/gradle/wrapper/gradle-wrapper.properties`.

**La profundidad medida no corresponde con la real**

Ajusta la constante `BASE_MM` en el firmware según la altura a la que hayas montado el sensor respecto a la superficie de compresión.
