# create_test_pdf.py
from reportlab.pdfgen import canvas

c = canvas.Canvas("test2.pdf")
c.drawString(100, 750, "Test Document for RAG Chatbot")
c.drawString(100, 730, "This is a test PDF with information about AI.")
c.drawString(100, 710, "Artificial Intelligence is transforming industries.")
c.drawString(100, 690, "Machine Learning is a subset of AI.")
c.drawString(100, 670, "Deep Learning uses neural networks.")
c.drawString(100, 650, "Natural Language Processing helps computers understand human language.")
c.drawString(100, 630, "Computer Vision enables machines to interpret visual information.")
c.drawString(100, 610, "Robotics combines AI with mechanical engineering.")
c.drawString(100, 590, "AI ethics is an important field of study.")
c.save()
print("✅ Created test.pdf with 8 lines of text")