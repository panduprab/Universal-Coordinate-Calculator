def classFactory(iface):
    from .plugin import TM3Plugin
    return TM3Plugin(iface)
