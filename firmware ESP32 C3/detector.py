# detector.py  ·  Detector de compresiones adaptativo  v3
#
# UN SOLO algoritmo para el banco de pruebas (diag.py) y para la
# operacion real (main.py).  Lo que se valida con el shaker es
# literalmente el codigo que corre con el maniqui.
#
# ---------------------------------------------------------------------
# Etapas, en cada muestra:
#
#   1. Filtro de mediana de 3 (opcional).  Elimina picos de ruido de una
#      sola muestra sin el retraso de un promedio movil.
#
#   2. Ventana movil de 'largo' muestras -> minimo y maximo.  El minimo
#      es el nivel de reposo; max - min es la amplitud reciente.
#
#   3. Umbrales como fraccion de la amplitud sobre el reposo:
#          alto = min + f_on  * (max - min)
#          bajo = min + f_off * (max - min)
#      Se adaptan solos: funcionan igual con el shaker (oscila entre 2.5
#      y 3.6 cm) que con el maniqui (oscila entre 0 y 6 cm).
#
#   4. Cruce de subida: cuando la senal pasa de 'alto'.  Su instante se
#      interpola linealmente entre la muestra anterior y la actual.  Se
#      usa el cruce y no el pico porque ahi la pendiente es maxima y la
#      resolucion de 1 mm del sensor produce el menor error temporal.
#
#   5. Antirrebote (opcional): exige 'debounce' muestras seguidas sobre
#      'alto' antes de confirmar, pero conserva el instante de la
#      PRIMERA para no introducir un retraso fijo.
#
#   6. Pico: maximo alcanzado mientras la senal esta en estado alto.
#      Es la profundidad de la compresion.
#
#   7. Cruce de bajada (pasa de 'bajo'): cierra el ciclo y emite evento.
#
#   8. CPM = (n - 1) * 60000 / (t_ultimo - t_primero) sobre los ultimos
#      'ventana_cpm' cruces de subida.
#
# ---------------------------------------------------------------------
# Cambios v3 respecto a la version usada en las primeras pruebas:
#
#   · Umbrales 40 % / 15 % de la amplitud sobre el reposo (antes
#     equivalian a 67.5 % / 32.5 %).  En RCP real la profundidad varia
#     entre compresiones; con el umbral anterior, tras una compresion de
#     6 cm el disparo quedaba en 4.05 cm y una de 4 cm no se detectaba.
#     Con 40 % queda en 2.4 cm.
#
#   · Reinicio de la ventana de CPM tras una pausa de mas de 'pausa_ms'.
#     Con la relacion 30:2 hay ~4 s de ventilaciones cada 30
#     compresiones; sin el reinicio, ese intervalo entraba en el promedio
#     y el CPM reportado caia a ~35 durante las 4 compresiones
#     siguientes.  El shaker no hace pausas, asi que no afecta al banco.

import time
from array import array


class Detector:

    def __init__(self, largo=100, f_on=0.40, f_off=0.25, debounce=2,
                 filtro=True, amp_min=0.60, ventana_cpm=5,
                 pausa_ms=1500, refresco=4):
        """
        largo       muestras de la ventana movil; debe cubrir al menos un
                    periodo completo.  100 a 66 Hz = 1.5 s (hasta 40 cpm)
        f_on        fraccion de amplitud sobre el reposo para disparar
        f_off       fraccion de amplitud sobre el reposo para rearmar.
                    SUBIRLA facilita el rearme (la senal tiene que bajar
                    menos); bajarla lo dificulta.  Medido en banco: con
                    0.15 la linea quedaba en 1.71 cm mientras el fondo de
                    la senal variaba entre 1.50 y 1.80, asi que algunos
                    ciclos no alcanzaban a cruzarla y se perdia esa
                    compresion (aparecian periodos del doble de largo).
                    Con 0.25 queda en 1.85 cm y siguen sobrando 2.1 mm de
                    separacion con la linea 'alto', bastante mas que el
                    ruido de 1 mm del sensor.
        debounce    muestras seguidas para confirmar (1 = desactivado)
        filtro      True aplica mediana de 3 muestras
        amp_min     amplitud minima (cm) para considerar que hay
                    compresiones; por debajo el detector no dispara
        ventana_cpm cruces sobre los que se promedia el CPM
        pausa_ms    un intervalo mayor reinicia la ventana de CPM
        refresco    cada cuantas muestras se recalculan min y max
        """
        self.largo = largo
        self.f_on = f_on
        self.f_off = f_off
        self.debounce = debounce
        self.filtro = filtro
        self.amp_min = amp_min
        self.ventana_cpm = ventana_cpm
        self.pausa_ms = pausa_ms
        self.refresco = refresco

        # ventana movil
        self.buf = array('f', [0.0] * largo)
        self.idx = 0
        self.llenas = 0
        self.desde_refresco = 0
        self.vmin = 0.0
        self.amp = 0.0
        self.valido = False

        # filtro de mediana
        self.r0 = self.r1 = self.r2 = 0.0
        self.tm1 = self.tm2 = 0

        # maquina de estados
        self.alto_estado = False
        self.cont_arriba = 0
        self.cand_t = 0
        self.d_prev = 0.0
        self.t_prev = 0
        self.iniciado = False

        # ciclo actual
        self.pico = 0.0
        self.t_subida = 0
        self.cruces = []

    # ------------------------------------------------------------------
    def _mediana3(self, a, b, c):
        if a > b:
            a, b = b, a
        if b > c:
            b, c = c, b
        if a > b:
            a, b = b, a
        return b

    # ------------------------------------------------------------------
    def _recalcular(self):
        """Piso y amplitud de la ventana.  Es la unica parte O(n) del
        detector, por eso se ejecuta cada 'refresco' muestras y no en
        todas: el nivel de reposo cambia mucho mas lento que la senal.

        Se usan el SEGUNDO minimo y el SEGUNDO maximo, no los extremos.
        Con los extremos, una sola lectura ruidosa definia el piso: si el
        fondo normal de la senal era 1.50 cm y el ruido producia un 1.40
        suelto, la linea 'bajo' quedaba por debajo del fondo real y el
        detector no se podia rearmar hasta que esa lectura salia de la
        ventana -- de ahi huecos de 1.5 a 2 s sin detectar nada.
        """
        if self.llenas < self.largo:
            self.valido = False
            return
        buf = self.buf
        m1 = m2 = 1e9
        x1 = x2 = -1e9
        for i in range(self.largo):
            v = buf[i]
            if v < m1:
                m2 = m1
                m1 = v
            elif v < m2:
                m2 = v
            if v > x1:
                x2 = x1
                x1 = v
            elif v > x2:
                x2 = v
        self.vmin = m2
        self.amp = x2 - m2
        self.valido = self.amp >= self.amp_min

    # ------------------------------------------------------------------
    def procesar(self, crudo, ahora=None):
        """Procesa una muestra de profundidad en cm.

        Devuelve None, o un diccionario al cerrarse una compresion:
            pico      profundidad maxima del ciclo (cm)
            t_subida  instante del cruce de subida (ms)
            periodo   ms desde el cruce anterior (0 si no hay)
            cpm       compresiones por minuto (0 si aun no hay 2 cruces)
        """
        if ahora is None:
            ahora = time.ticks_ms()

        # ---------- 1. filtro de mediana ----------
        # la salida corresponde a la muestra CENTRAL de las tres, asi que
        # tambien se le asigna la marca de tiempo central
        self.r0, self.r1, self.r2 = self.r1, self.r2, crudo
        self.tm1, self.tm2 = self.tm2, ahora
        if self.filtro:
            d = self._mediana3(self.r0, self.r1, self.r2)
            t_d = self.tm1
        else:
            d = crudo
            t_d = ahora

        # ---------- 2. ventana movil ----------
        self.buf[self.idx] = d
        self.idx = (self.idx + 1) % self.largo
        if self.llenas < self.largo:
            self.llenas += 1
        self.desde_refresco += 1
        if self.desde_refresco >= self.refresco:
            self.desde_refresco = 0
            self._recalcular()

        if not self.iniciado or not self.valido:
            self.iniciado = True
            self.d_prev = d
            self.t_prev = t_d
            return None

        # ---------- 3. umbrales ----------
        alto = self.vmin + self.f_on * self.amp
        bajo = self.vmin + self.f_off * self.amp
        evento = None

        # ---------- 6. pico ----------
        if self.alto_estado and d > self.pico:
            self.pico = d

        # ---------- 4 y 5. cruce de subida con antirrebote ----------
        if not self.alto_estado:
            if d > alto:
                self.cont_arriba += 1
                if self.cont_arriba == 1:
                    # instante candidato por interpolacion lineal
                    if d != self.d_prev:
                        f = (alto - self.d_prev) / (d - self.d_prev)
                        if f < 0.0:
                            f = 0.0
                        elif f > 1.0:
                            f = 1.0
                    else:
                        f = 0.0
                    dt = time.ticks_diff(t_d, self.t_prev)
                    self.cand_t = self.t_prev + int(f * dt)

                if self.cont_arriba >= self.debounce:
                    self.alto_estado = True
                    self.cont_arriba = 0
                    self.t_subida = self.cand_t
                    self.pico = d

                    # reinicio tras pausa
                    if self.cruces and time.ticks_diff(
                            self.t_subida, self.cruces[-1]) > self.pausa_ms:
                        self.cruces = []

                    self.cruces.append(self.t_subida)
                    if len(self.cruces) > self.ventana_cpm:
                        self.cruces.pop(0)
            else:
                self.cont_arriba = 0

        # ---------- 7 y 8. cruce de bajada: cierra el ciclo ----------
        elif d < bajo:
            self.alto_estado = False

            if len(self.cruces) >= 2:
                span = time.ticks_diff(self.cruces[-1], self.cruces[0])
                cpm = (len(self.cruces) - 1) * 60000.0 / span if span > 0 else 0.0
                periodo = time.ticks_diff(self.cruces[-1], self.cruces[-2])
            else:
                cpm = 0.0
                periodo = 0

            evento = {"pico": self.pico,
                      "t_subida": self.t_subida,
                      "periodo": periodo,
                      "cpm": cpm}
            self.pico = 0.0

        self.d_prev = d
        self.t_prev = t_d
        return evento
