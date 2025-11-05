// Tailwind em modo escuro com o tema
module.exports = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "#d90429",
        dark: "#0f0f0f",
        mid: "#151515",
        card: "#1e1e1e",
        light: "#ffffff"
      },
      boxShadow: {
        soft: "0 10px 25px rgba(0,0,0,0.25)"
      }
    }
  },
  plugins: []
}
