# Jellyfin TV Stream

We've got a really good base here. But my overall objective was always to surface this in my Jellyfin instance so that I could stream the TV channel to my CRT displays. Let's plan how to do this.

Some constraints:
- Keep as much of the implementation in Python code as possible (modules containing native C or other code/bindings are fine!)
- Document it deeply
- Keep any python code we write for this in a separate part of the codebase that can be easily ripped out (e.g. deleting the code has no impact on the function of the app)
- The stream to Jellyfin should include video and audio
- It should stream in a format I can hardware decode/encode with a TuringPi RK1 (e.g. RMPP on the RK1 VPU/RK3588 chipset)
- Ultimately I'll be deploying this into a container running on my Nomad cluster in Docker - so keep that in mind

Ask me anything you need to know before planning an approach.
