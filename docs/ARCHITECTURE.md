# Architecture and boundaries

`studio.py` owns the Tk application, background media work and upload scheduling. `studio_core.py` prepares GIFs, reads Windows SMTC/system statistics, stores settings and provides the tray. `screen_ui.py` draws 160×96 frames. `keyboard_usb.py` discovers the exact verified unit and performs complete HID transactions. The i18n catalogues translate application-generated text.

The screen path is:

```text
Windows media / system data → Pillow renderer → RGB565 animation
  → complete USB transfer → keyboard animation player
```

It is not:

```text
small semantic updates → custom firmware widgets → uninterrupted redraw
```

The second architecture is the intended research direction, not an implemented feature. A native renderer requires an identified stock protocol handler or target-specific firmware work. The exact MCU, panel connections, firmware image and recovery method have not been verified for this unit. General SONiX ISP strings in the Windows application are not a working updater.

The inspected driver has a fast feature stream for **per-key RGB lighting**. It is not evidence of LCD RAM, text or partial-rectangle support. Transaction commands occur across several subsystems; static host code alone does not identify which command triggers the physical loading screen.

No vendor application code, firmware image, board dump or QMK code is redistributed here. The repository implements independently inspected host-side behavior and records a narrow hardware compatibility boundary.
