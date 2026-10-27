"""Standalone Google Cast connectivity test, unrelated to IPTV credentials."""
import pychromecast

TEST_VIDEO = 'https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4'


def main():
    print('Buscando Google TV…')
    devices, browser = pychromecast.get_chromecasts(timeout=8, tries=2)
    try:
        if not devices:
            print('No hay dispositivos Google Cast disponibles')
            return
        for i, dev in enumerate(devices, 1):
            print(f'{i}: {dev.cast_info.friendly_name} ({dev.cast_info.host})')
        idx = int(input('Número de dispositivo: ')) - 1
        cast = devices[idx]
        print('Conectando…')
        cast.wait(timeout=15)
        print('Conexión establecida; enviando MP4 público…')
        cast.media_controller.play_media(TEST_VIDEO, 'video/mp4')
        cast.media_controller.block_until_active(timeout=20)
        state = cast.media_controller.status
        print(f'Estado={state.player_state}, motivo={state.idle_reason}')
        input('Pulsa Intro para terminar la prueba (detendrá el vídeo)…')
        cast.media_controller.stop()
    finally:
        for dev in devices:
            try:
                dev.disconnect()
            except Exception:
                pass
        browser.stop_discovery()


if __name__ == '__main__':
    main()
