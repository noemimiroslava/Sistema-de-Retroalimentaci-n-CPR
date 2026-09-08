//  main.dart – WS-CPR ► BLE-CPR
//  Se conecta al servicio 19B1:0002 y consume las características:
//  • 0003 PROFUNDIDAD (float little-endian, notify 20 Hz)
//  • 0004 FRECUENCIA  (float little-endian, notify cada compresión)
//  • 0005 MODE        (write TRAIN / EVAL)
//  Requiere flutter_blue_plus ^2.3.12 y permission_handler ^11.4.0

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';
import 'package:syncfusion_flutter_gauges/gauges.dart';
import 'package:just_audio/just_audio.dart';
import 'package:shared_preferences/shared_preferences.dart';


void main() {
  FlutterBluePlus.setLogLevel(LogLevel.verbose, color: true);
  runApp(const MyApp());
}

/* ═════════════════════ CONSTANTES BLE ═════════════════════ */
const _deviceName = 'ESP32-Noemi';
final Guid _svcUuid   = Guid('19b10002-e8f2-537e-4f6c-d104768a1214');
final Guid _profUuid  = Guid('19b10003-e8f2-537e-4f6c-d104768a1214');
final Guid _freqUuid  = Guid('19b10004-e8f2-537e-4f6c-d104768a1214');
final Guid _modeUuid  = Guid('19b10005-e8f2-537e-4f6c-d104768a1214');

/* ═════════════════════ BLE WRAPPER ════════════════════════ */
class BleMsg {
  final double cpm;
  final double peak;
  final double prof;
  const BleMsg.prof(this.prof) : peak = 0, cpm  = 0;
  const BleMsg.comp(this.peak, this.cpm) : prof = 0;
}

class BleChannel {
  final BluetoothDevice dev;
  final BluetoothCharacteristic profC;
  final BluetoothCharacteristic dataC;
  final BluetoothCharacteristic modeC;

  final _ctrl = StreamController<BleMsg>.broadcast();
  Stream<BleMsg> get stream => _ctrl.stream;

  BleChannel(this.dev, this.profC, this.dataC, this.modeC);

  Future<void> init() async {
    await profC.setNotifyValue(true);
    await dataC.setNotifyValue(true);

    profC.lastValueStream.listen((d) {
      final v = ByteData.sublistView(Uint8List.fromList(d))
          .getFloat32(0, Endian.little);
      _ctrl.add(BleMsg.prof(v));
    });
    dataC.lastValueStream.listen((d) {
      final bd   = ByteData.sublistView(Uint8List.fromList(d));
      final peak = bd.getFloat32(0, Endian.little);
      final cpm  = bd.getFloat32(4, Endian.little);
      _ctrl.add(BleMsg.comp(peak,cpm));
    });
  }

  Future<void> sendMode(bool train) async =>
      modeC.write(utf8.encode(train ? 'TRAIN' : 'EVAL'));

  Future<void> dispose() async {
    await dev.disconnect();
    await _ctrl.close();
  }
}

/* ═════════════════════ APP ROOT ═══════════════════════════ */
class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'WS-CPR BLE',
        theme: ThemeData.light(useMaterial3: true),
        home: const ConnectPage(),
      );
}

/* ═════════════════════ CONNECT PAGE ═══════════════════════ */
class ConnectPage extends StatefulWidget {
  const ConnectPage({super.key});
  @override
  State<ConnectPage> createState() => _ConnectPageState();
}

class _ConnectPageState extends State<ConnectPage> {
  String _status = 'Sin conectar';

  Future<bool> _perms() async {
    final req = [
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
    ];
    final res = await req.request();
    return res.values.every((p) => p.isGranted);
  }

  Future<void> _connect() async {
    setState(() => _status = 'Buscando BLE…');
    try {
      if (!await _perms()) {
        setState(() => _status = 'Permisos denegados');
        return;
      }

      await FlutterBluePlus.startScan(withServices: [_svcUuid]); 

      final res = await FlutterBluePlus.scanResults
          .expand((e) => e)
          .firstWhere((r) => r.device.platformName == _deviceName)
          .timeout(const Duration(seconds: 10),
              onTimeout: () => throw 'ESP32 no encontrado');
      await FlutterBluePlus.stopScan();

      final dev = res.device;
      await dev.connect(
          license: License.nonprofit, timeout: const Duration(seconds: 8));
      final svc = (await dev.discoverServices())
          .firstWhere((s) => s.uuid == _svcUuid);

      final chProf = svc.characteristics
          .firstWhere((c) => c.uuid == _profUuid);
      final chFreq = svc.characteristics
          .firstWhere((c) => c.uuid == _freqUuid);
      final chMode = svc.characteristics
          .firstWhere((c) => c.uuid == _modeUuid);

      final ble = BleChannel(dev, chProf, chFreq, chMode);
      await ble.init();

      if (!mounted) return;

      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) => Provider.value(
            value: ble,
            child: const ModeSelection(),
          ),
        ),
      );
    } catch (e) {
      await FlutterBluePlus.stopScan();
      if (mounted) setState(() => _status = 'Error: $e');
    }
  }

  @override
  Widget build(BuildContext ctx) => Scaffold(
        appBar: AppBar(title: const Text('')),
        body: Center(
          child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Text(' Aplicación para la evaluación \n'' o entrenamiento de la\n' ' técnica de reanimación \n'
               'cardiopulmonar de acuerdo \n''a las guías de la AHA 2020 \n',textAlign: TextAlign.center,
                  style: TextStyle(
                      fontSize: 25,
                      fontWeight: FontWeight.w700,
                      color: Colors.black)),
              const SizedBox(height: 24),
        Image.asset(
          'assets/logo1.png',
          width: 180,
          fit: BoxFit.contain,
        ),
              const Text('Enciende tu Bluetooth \n' 'para conectarte con la ESP32\n',textAlign: TextAlign.center,
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700)),
              ElevatedButton.icon(
                icon: const Icon(Icons.bluetooth_searching),
                label: const Text('Conectar'),
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white),
                onPressed: _connect,
              ),
              const SizedBox(height: 12),
              Text(_status),
              const SizedBox (height:12),
            ElevatedButton.icon(
                icon: const Icon(Icons.history),
                label: const Text('Ver últimas sesiones'),
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white),
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const LastSessionsPage()),
                ),
              
        )
            ],
          ),
        ),
      );
}

/* ═════════════════════ MODO (TRAIN / EVAL) ════════════════ */
enum SessionMode { eval, train }

class ModeSelection extends StatelessWidget {
  const ModeSelection({super.key});
  @override
  Widget build(BuildContext context) {
    final ble = Provider.of<BleChannel>(context, listen: false);
    return Scaffold(
      appBar: AppBar(title: const Text('Modo')),
      body: Center(
        child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text(
              'Relación:\n'
                'Compresiones:Respiraciones\n'
                '30:2\n'
                '\n'
                'Tiempo ⏳ : 60 segundos\n'
                '\n'
                'Retroalimentación del Metronomo:\n'
                '100 cpm \n'
                '\n'
                'Retroalimentación del Led:\n'
          
                'Led Verde 🟢 : Profundidad Correcta [5 - 6 cm]\n'
                'Led Rojo  🔴 : Profundidad Incorrecta\n'
                '\n'
                'Elige un modo\n',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 25),
            ElevatedButton(
              onPressed: () => _start(context, ble, SessionMode.eval),
              child: const Text('Evaluación'), 
              style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white),
            ),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: () => _start(context, ble, SessionMode.train),
              child: const Text('Entrenamiento'),
              style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white),
            ),
            const SizedBox (height:12),
            ElevatedButton.icon(
                icon: const Icon(Icons.history),
                label: const Text('Ver últimas sesiones'),
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white),
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const LastSessionsPage()),
                ),
              
        )],
        ),
      ),
    ));
  }

  void _start(BuildContext ctx, BleChannel ble, SessionMode mode) async {
    await ble.sendMode(mode == SessionMode.train);
    Navigator.of(ctx).pushReplacement(
      MaterialPageRoute(
        builder: (_) => ChangeNotifierProvider(
          create: (_) => SessionControllerBle(mode, ble),
          child: const CprSession(),
        ),
      ),
    );
  }
}

/* ═════════════════════ CONTROLADOR DE SESIÓN (BLE) ═══════ */
class SessionControllerBle extends ChangeNotifier {
  final SessionMode mode;
  final BleChannel ble;
  late final StreamSubscription _sub;

  double depth = 0, bpm = 0, freqHz = 0;
  double freqSum = 0, depthSum = 0;
  int    freqCount = 0, correctComp = 0, totalComp = 0;
  int    fullCyclesMs = 0, lastCycleEnd = 0;
  bool   _started = false, _finished = false;
  late final Timer _timeoutTimer;

  final AudioPlayer _player = AudioPlayer();
  bool _tickLoaded = false, _soundPlaying = false;
  final Stopwatch _timer = Stopwatch();

  SessionControllerBle(this.mode, this.ble) {
    _initSound();
    _sub = ble.stream.listen(_onMsg);
  }

  Future<void> _initSound() async {
    try {
      await _player.setAsset('assets/tick.wav');
      _player.setLoopMode(LoopMode.one);
      _tickLoaded = true;
    } catch (_) {}
  }

  void _onMsg(BleMsg m) async {
  final now = DateTime.now().millisecondsSinceEpoch;

  if (m.cpm == 0 && m.peak == 0) {
    depth = m.prof.clamp(0, 6);
    notifyListeners();
    return;
  }

  final peak = m.peak;
  final cpm  = m.cpm;

  if (!_started && m.peak > 0) {
    _started = true;
    _timer.start();
    lastCycleEnd = now;

    _timeoutTimer = Timer(const Duration(seconds: 60), _finish);

    if (mode == SessionMode.train && _tickLoaded && !_soundPlaying) {
      _soundPlaying = true;
      await _player.play();
    }
  }

  depth     = m.peak.clamp(0, 6);

  if (m.cpm > 0) {
    bpm       = m.cpm;
    freqHz    = m.cpm / 60;
    freqSum  += m.cpm;
    freqCount++;

    totalComp++;
    depthSum += peak;
    if (peak >= 5 && peak <= 6) correctComp++;

    fullCyclesMs += now - lastCycleEnd;
    lastCycleEnd  = now;
  }

  if (!_finished && _timer.elapsedMilliseconds >= 60000) {
    _finish();
  }

  notifyListeners();
}

  bool get finished => _finished;
  int  get remaining => (60 - _timer.elapsed.inSeconds).clamp(0, 60);

  int    get correct => correctComp;
  int    get total   => totalComp;
  double get avgCpm  => freqCount == 0 ? 0 : freqSum / freqCount;
  double get avgDepth=> totalComp == 0 ? 0 : depthSum / totalComp;
  double get fracCp  => fullCyclesMs / 60000.0;

  Future<void> _finish() async {
  if (_finished) return;
  _finished = true;
  _timeoutTimer.cancel();
  await _sub.cancel();
  if (_soundPlaying) await _player.stop();
  notifyListeners();
}

  @override
  void dispose() {
    _timeoutTimer.cancel();
    _sub.cancel();
    _player.dispose();
    ble.dispose();
    super.dispose();
  }
}

/* ═════════════════════ UI – SESIÓN CPR ═══════════════════ */
class CprSession extends StatelessWidget {
  const CprSession({super.key});
  @override
  Widget build(BuildContext context) {
    final ctl = context.watch<SessionControllerBle>();

    if (ctl.finished) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => SummaryPage(
              correct:  ctl.correct,
              total:    ctl.total,
              freqAvg:  ctl.avgCpm,
              depthAvg: ctl.avgDepth,
            ),
          ),
        );
      });
    }

    return Scaffold(backgroundColor: Colors.black,
      appBar: AppBar(
        title: Text(ctl.mode == SessionMode.train ? 'Entrenamiento' : 'Evaluación'),
      ),
      body: Center(
        child: SingleChildScrollView(child: DefaultTextStyle(
        style: const TextStyle(
          color: Colors.white
        ),
          child: Column(
            children: [
              DepthBar(depthCm: ctl.depth),
              const SizedBox(height: 8),
              Text('${ctl.depth.toStringAsFixed(1)} cm'),
              const SizedBox(height: 8),
              Text('Hz: ${ctl.freqHz.toStringAsFixed(2)}'),
              Text('cpm: ${ctl.bpm.toStringAsFixed(0)}'),
              const SizedBox(height: 24),
              SizedBox(width: 180, height: 180, child: CpmGauge(ctl.bpm)),
              if (ctl.remaining > 0) ...[
                const SizedBox(height: 24),
                Text('Tiempo restante: ${ctl.remaining}s'),
              ],
            ],
          ),
        ),
      ),
    ));
  }
}

/* ═════════════════════ WIDGETS VISUALES ══════════════════ */
class DepthBar extends StatelessWidget {
  final double depthCm;
  const DepthBar({super.key, required this.depthCm});
  @override
  Widget build(BuildContext context) {
    const barH = 180.0;
    final y = (depthCm / 6) * barH;
    Widget lbl(String t) => Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(border: Border.all(color: Colors.teal)),
          child: Text(t),
        );
    return Column(children: [
      lbl('descompresión'), const SizedBox(height: 6),
      Stack(children: [
        Container(height: barH, width: 60, color: Colors.black12),
        Positioned(
            top: y,
            left: 0,
            right: 0,
            child:
                Container(height: 24, color: Colors.white)),
      ]),
      const SizedBox(height: 6), lbl('compresión')
    ]);
  }
}

class CpmGauge extends StatelessWidget {
  final double bpm;
  const CpmGauge(this.bpm, {super.key});
  @override
  Widget build(BuildContext ctx) => SfRadialGauge(axes: [
        RadialAxis(
          minimum: 30,
          maximum: 181,
          interval: 30,
          axisLabelStyle: const GaugeTextStyle(
              color : Colors.white),
          ranges: [
            GaugeRange(
                startValue: 30,
                endValue: 99,
                color: Colors.red,
                startWidth: 0.25,
                endWidth: .25,
                sizeUnit: GaugeSizeUnit.factor),
            GaugeRange(
                startValue: 100,
                endValue: 120,
                color: Colors.green,
                startWidth: .25,
                endWidth: .25,
                sizeUnit: GaugeSizeUnit.factor),
            GaugeRange(
                startValue: 121,
                endValue: 180,
                color: Colors.red,
                startWidth: .25,
                endWidth: .25,
                sizeUnit: GaugeSizeUnit.factor),
          ],
          pointers: [NeedlePointer(value: bpm.clamp(30, 180),needleColor: Colors.white, knobStyle: const KnobStyle(color: Colors.white))],
          annotations: [
            GaugeAnnotation(
                widget: Text('${bpm.toStringAsFixed(0)}',
                    style: const TextStyle(fontSize: 24)),
                angle: 90,
                positionFactor: .8)
          ],
        )
      ]);
}

/* ───── Barra de profundidad detallada ─────────────────── */
class _DepthBar extends StatelessWidget {
  final double avg;

  const _DepthBar(this.avg, {super.key});

  @override
  Widget build(BuildContext context) {
    final double fullW = MediaQuery.of(context).size.width * 0.85;
    final double posX  = (avg.clamp(0, 8) / 8) * fullW;

    return SizedBox(
      width: fullW,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          CustomPaint(
            size: Size(fullW, 25),
            painter: _DepthPainter(),
          ),

          Positioned(
            left: posX - 18,
            top: -14,
            child: Column(
              children: [
                const Icon(Icons.arrow_drop_down, size: 28, color: Colors.blue),
                Container(width: 2, height: 18, color: Colors.blue),
              ],
            ),
          ),
        ],
      ),

    );
  }
}

/* ───── Pintor de la barra ─────────────────────────────── */
class _DepthPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size sz) {
    const barH = 18.0;
    const totalCm = 8;

    final Paint red   = Paint()..color = Colors.red;
    final Paint green = Paint()..color = Colors.green;

    canvas.drawRect(
      Rect.fromLTWH(0, 0, sz.width * 5 / totalCm, barH),
      red,
    );
    canvas.drawRect(
      Rect.fromLTWH(sz.width * 5 / totalCm, 0, sz.width / totalCm, barH),
      green,
    );
    canvas.drawRect(
      Rect.fromLTWH(sz.width * 6 / totalCm, 0, sz.width * 2 / totalCm, barH),
      red,
    );

    final Paint tick = Paint()
      ..color = Colors.black
      ..strokeWidth = 1;

    final textStyle = const TextStyle(fontSize: 10, color: Colors.black);

    for (int cm = 0; cm <= totalCm; cm++) {
      final double x = cm * sz.width / totalCm;
      canvas.drawLine(Offset(x, barH), Offset(x, barH + 6), tick);
      final tp = TextPainter(
        text: TextSpan(text: '$cm', style: textStyle),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(x - tp.width / 2, barH + 6));
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/* ═════════════════════ RESUMEN ═══════════════════════════ */
class SummaryPage extends StatelessWidget {
  final int    correct, total;
  final double freqAvg, depthAvg;

  const SummaryPage({
    super.key,
    required this.correct,
    required this.total,
    required this.freqAvg,
    required this.depthAvg,
  });

  double _pctCorrect() => total == 0 ? 0 : correct / total;

  double _pctFreq() {
    final diff = (freqAvg < 100)
        ? 100 - freqAvg
        : (freqAvg > 120 ? freqAvg - 120 : 0);
    return (1 - diff / 10 * .10).clamp(0, 1);
  }

  double _pctDepth() {
    double diff = 0;
    if (depthAvg < 5) diff = 5 - depthAvg;
    if (depthAvg > 6) diff = depthAvg - 6;
    return (1 - diff / .5 * .10).clamp(0, 1);
  }

  int _score() => (((_pctCorrect() + _pctFreq() + _pctDepth()) / 3) * 100).round();

  Widget _ring(double val, Color ringColor, double size,
      {String? suffix, Color textColor = Colors.black}) =>
      SizedBox(
        width: size,
        height: size,
        child: SfRadialGauge(axes: [
          RadialAxis(
            minimum: 0,
            maximum: 100,
            startAngle: 270,
            endAngle: 270,
            showTicks: false,
            showLabels: false,
            axisLineStyle: const AxisLineStyle(
              thickness: .18,
              thicknessUnit: GaugeSizeUnit.factor,
            ),
            pointers: [
              RangePointer(
                value: val,
                width: .18,
                sizeUnit: GaugeSizeUnit.factor,
                color: ringColor,
                cornerStyle: CornerStyle.bothFlat,
              )
            ],
            annotations: [
              GaugeAnnotation(
                widget: suffix == null
                    ? Text(val.toStringAsFixed(0),
                        style: TextStyle(
                            fontSize: 28,
                            fontWeight: FontWeight.bold,
                            color: textColor))
                    : RichText(
                        text: TextSpan(children: [
                        TextSpan(
                            text: val.toStringAsFixed(0),
                            style: TextStyle(
                                fontSize: 28,
                                fontWeight: FontWeight.bold,
                                color: textColor)),
                        TextSpan(
                            text: ' $suffix',
                            style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                                color: textColor)),
                      ])),
                angle: 90,
                positionFactor: 0,
              ),
            ],
          )
        ]),
      );

  @override
  Widget build(BuildContext context) {
    Future.microtask(() async {
      await HistoryStore.add(SessionSummary(
        ts: DateTime.now(),
        score: _score(),
        correct: correct,
        total: total,
        avgCpm: freqAvg,
        avgDepth: depthAvg,
      ));
    });

    final w = MediaQuery.of(context).size.width;
    final gSz = w * .42;
    final pctCorrect100 = (_pctCorrect() * 100).roundToDouble();

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: const Text('Resumen'),
        backgroundColor: Colors.white,
        foregroundColor: Colors.black,
        elevation: 0,
      ),
      body: Center(
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('Calificación Total',
                  style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                      color: Colors.black)),
              _ring(_score().toDouble(), Colors.blue, gSz,
                  textColor: Colors.black),

              const SizedBox(height: 8),
              const Text('Porcentaje de compresiones correctas',
                  style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Colors.black)),
              _ring(pctCorrect100, Colors.purple, gSz * .8,
                  suffix: '%', textColor: Colors.black),
              Text('$correct compresiones correctas de $total totales',
                  style: const TextStyle(fontSize: 14, color: Colors.black)),

              const SizedBox(height: 8),
              const Text('Promedio de Compresiones por minuto',
                  style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Colors.black)),
              SizedBox(
                width: gSz,
                height: gSz,
                child: SfRadialGauge(axes: [
                  RadialAxis(
                    minimum: 60,
                    maximum: 160,
                    startAngle: 180,
                    endAngle: 0,
                    showTicks: false,
                    showLabels: false,
                    ranges: [
                      GaugeRange(
                          startValue: 60,
                          endValue: 100,
                          color: Colors.red,
                          startWidth: .75,
                          endWidth: .75,
                          sizeUnit: GaugeSizeUnit.factor),
                      GaugeRange(
                          startValue: 100,
                          endValue: 120,
                          color: Colors.green,
                          startWidth: .75,
                          endWidth: .75,
                          sizeUnit: GaugeSizeUnit.factor),
                      GaugeRange(
                          startValue: 120,
                          endValue: 180,
                          color: Colors.amber,
                          startWidth: .75,
                          endWidth: .75,
                          sizeUnit: GaugeSizeUnit.factor),
                     
                    ],
                    
                    pointers: [
                      NeedlePointer(
                          value: freqAvg.clamp(60, 160),
                          needleColor: Colors.black,
                          knobStyle: const KnobStyle(color: Colors.black)),
                    ],
                  
        annotations: [
          GaugeAnnotation(
            widget: const Text(
              'Muy lento',
              style: TextStyle(color: Colors.black, fontSize: 12),
            ),
            angle          : 150,
            positionFactor : .8,
          ),
          GaugeAnnotation(
            widget: const Text(
              'Muy rápido',
              style: TextStyle(color: Colors.black, fontSize: 12),
            ),
            angle          : 30,
            positionFactor : .8,
          )],
                  )
                ]),
              ),
              Text(
                  'Promedio de compresiones por minuto: '
                  '${freqAvg.toStringAsFixed(0)}',
                  style:
                      const TextStyle(fontSize: 14, color: Colors.black)),

              const SizedBox(height: 8),
              const Text('Profundidad promedio',
                  style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Colors.black)),
              const SizedBox(height: 4),
              _DepthBar(depthAvg),
              const SizedBox(height: 4),
              Text('${depthAvg.toStringAsFixed(1)} cm',
                  style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Colors.black)),

              const SizedBox(height: 8),
              ElevatedButton.icon(
                icon: const Icon(Icons.refresh),
                label: const Text('Reiniciar'),
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white),
                onPressed: () => Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const ConnectPage()),
                  (_) => false,
                ),
              ),
              ElevatedButton.icon(
                icon: const Icon(Icons.history),
                label: const Text('Ver últimas sesiones'),
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white),
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const LastSessionsPage()),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class SessionSummary {
  final DateTime ts;
  final int score, correct, total;
  final double avgCpm, avgDepth;

  SessionSummary({
    required this.ts,
    required this.score,
    required this.correct,
    required this.total,
    required this.avgCpm,
    required this.avgDepth,
  });

  Map<String, dynamic> toJson() => {
        'ts': ts.toIso8601String(),
        'score': score,
        'correct': correct,
        'total': total,
        'avgCpm': avgCpm,
        'avgDepth': avgDepth,
      };

  factory SessionSummary.fromJson(Map<String, dynamic> j) => SessionSummary(
        ts       : DateTime.parse(j['ts']),
        score    : j['score'],
        correct  : j['correct'],
        total    : j['total'],
        avgCpm   : (j['avgCpm'] as num).toDouble(),
        avgDepth : (j['avgDepth'] as num).toDouble(),
      );
}

class HistoryStore {
  static const _key = 'cpr_history';

  static Future<List<SessionSummary>> load() async {
    final sp   = await SharedPreferences.getInstance();
    final list = sp.getStringList(_key) ?? [];
    return list
        .map((s) => SessionSummary.fromJson(
              Map<String, dynamic>.from(jsonDecode(s)),
            ))
        .toList();
  }

  static Future<void> add(SessionSummary s) async {
    final sp   = await SharedPreferences.getInstance();
    final list = sp.getStringList(_key) ?? [];
    list.insert(0, jsonEncode(s.toJson()));
    if (list.length > 5) list.removeLast();
    await sp.setStringList(_key, list);
  }
}

class LastSessionsPage extends StatelessWidget {
  const LastSessionsPage({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Últimas 5 sesiones')),
        body: FutureBuilder<List<SessionSummary>>(
          future: HistoryStore.load(),
          builder: (ctx, snap) {
            if (!snap.hasData) {
              return const Center(child: CircularProgressIndicator());
            }
            final list = snap.data!;
            if (list.isEmpty) {
              return const Center(child: Text('Aún no hay sesiones'));
            }

            return ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (_, i) {
                final s   = list[i];
                final pct = (s.total == 0)
                    ? 0
                    : (s.correct / s.total * 100).round();

                return Card(
                  elevation: 2,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              _fmtDate(s.ts),
                              style: const TextStyle(
                                  fontWeight: FontWeight.w600, fontSize: 16),
                            ),
                            Text(
                              '${s.score}',
                              style: const TextStyle(
                                  fontWeight: FontWeight.bold, fontSize: 26),
                            ),
                          ],
                        ),
                        const Divider(),
                        _kv('Compresiones correctas', '$pct %'),
                        _kv('Correctas / Total', '${s.correct} / ${s.total}'),
                        _kv('Prom. CPM', s.avgCpm.toStringAsFixed(1)),
                        _kv('Prof. prom. (cm)', s.avgDepth.toStringAsFixed(1)),
                      ],
                    ),
                  ),
                );
              },
            );
          },
        ),
      );

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            Expanded(child: Text(k)),
            Text(v, style: const TextStyle(fontWeight: FontWeight.w500)),
          ],
        ),
      );

  String _fmtDate(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/'
      '${d.month.toString().padLeft(2, '0')}/'
      '${d.year.toString().substring(2)}  '
      '${d.hour.toString().padLeft(2, '0')}:'
      '${d.minute.toString().padLeft(2, '0')}';
}